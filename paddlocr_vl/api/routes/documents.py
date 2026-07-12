from __future__ import annotations

import shutil
from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from ...core.config import Settings
from ...core.dependencies import authorize, get_ocr_service, get_settings
from ...service import PaddleOCRVLService
from ...schemas import OutputFormat, ParseResponse
from ...utils.file_utils import (
    json_compatible,
    save_upload,
    validate_image_upload,
    validate_upload,
)

router = APIRouter(tags=["documents"], dependencies=[Depends(authorize)])


async def _parse_document(
    file: UploadFile,
    settings: Settings,
    ocr_service: PaddleOCRVLService,
    output_format: OutputFormat,
    extension: str,
) -> JSONResponse:
    request_id = uuid.uuid4().hex
    upload_path = settings.upload_dir / f"{request_id}{extension}"
    output_dir = settings.output_dir / request_id
    try:
        size = await save_upload(file, upload_path, settings.max_file_size_bytes)
        try:
            result = await run_in_threadpool(
                ocr_service.predict, upload_path, output_dir
            )
        except Exception as exc:
            raise HTTPException(502, f"Document parsing failed: {exc}") from exc
        response: dict[str, object] = {
            "request_id": request_id,
            "filename": file.filename,
            "content_type": file.content_type,
            "file_size_bytes": size,
            "processed_pages": result["processed_pages"],
        }
        if output_format in {OutputFormat.JSON, OutputFormat.BOTH}:
            response["pages"] = [
                {"page": page["page"], "json": page["json"]}
                for page in result["pages"]
            ]
        if output_format in {OutputFormat.MARKDOWN, OutputFormat.BOTH}:
            response["combined_markdown"] = result["combined_markdown"]
            if output_format is OutputFormat.BOTH:
                response["pages"] = result["pages"]
        return JSONResponse(json_compatible(response))
    finally:
        if settings.delete_temp_files:
            upload_path.unlink(missing_ok=True)
            shutil.rmtree(output_dir, ignore_errors=True)


@router.post(
    "/parse/image",
    response_model=ParseResponse,
    response_model_exclude_none=True,
)
async def parse_image(
    file: Annotated[UploadFile, File(...)],
    settings: Annotated[Settings, Depends(get_settings)],
    ocr_service: Annotated[PaddleOCRVLService, Depends(get_ocr_service)],
) -> JSONResponse:
    extension = validate_image_upload(file)
    return await _parse_document(
        file, settings, ocr_service, OutputFormat.BOTH, extension
    )


@router.post(
    "/parse/pdf",
    response_model=ParseResponse,
    response_model_exclude_none=True,
)
async def parse_pdf(
    file: Annotated[UploadFile, File(...)],
    settings: Annotated[Settings, Depends(get_settings)],
    ocr_service: Annotated[PaddleOCRVLService, Depends(get_ocr_service)],
    output_format: Annotated[
        OutputFormat,
        Query(description="Result content to include"),
    ] = OutputFormat.BOTH,
) -> JSONResponse:
    extension = validate_upload(file)
    if extension != ".pdf":
        raise HTTPException(415, "This endpoint accepts PDF files only")
    return await _parse_document(
        file, settings, ocr_service, output_format, extension
    )
