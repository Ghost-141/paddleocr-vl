from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse

from ...core.config import Settings
from ...core.dependencies import authorize, get_job_store, get_owner_id, get_settings
from ...db.jobs import JobStore, QueueFullError
from ...utils.pdf_utils import EncryptedPDFError, InvalidPDFError, inspect_pdf
from ...schemas import OutputFormat
from ...utils.file_utils import save_upload, validate_image_upload, validate_upload

router = APIRouter(tags=["documents"], dependencies=[Depends(authorize)])


@router.post("/parse/image", status_code=202)
async def parse_image(
    file: Annotated[UploadFile, File(...)],
    settings: Annotated[Settings, Depends(get_settings)],
    store: Annotated[JobStore, Depends(get_job_store)],
    owner_id: Annotated[str, Depends(get_owner_id)],
    output_format: Annotated[
        OutputFormat, Query(description="Artifact(s) to create")
    ] = OutputFormat.BOTH,
) -> JSONResponse:
    extension = validate_image_upload(file)
    upload_path = settings.upload_dir / f"{uuid.uuid4().hex}{extension}"
    try:
        await save_upload(file, upload_path, settings.max_file_size_bytes)
        try:
            job = store.create_job(
                owner_id=owner_id,
                filename=file.filename or f"image{extension}",
                output_format=output_format.value,
                total_pages=1,
                upload_path=upload_path,
                source_type="image",
            )
        except QueueFullError as exc:
            raise HTTPException(
                429, "Job queue is full", headers={"Retry-After": "60"}
            ) from exc
    except Exception:
        upload_path.unlink(missing_ok=True)
        raise
    return JSONResponse(_submission(job), status_code=202)


@router.post("/parse/pdf", status_code=202)
async def parse_pdf(
    file: Annotated[UploadFile, File(...)],
    settings: Annotated[Settings, Depends(get_settings)],
    store: Annotated[JobStore, Depends(get_job_store)],
    owner_id: Annotated[str, Depends(get_owner_id)],
    output_format: Annotated[
        OutputFormat, Query(description="Artifact(s) to create")
    ] = OutputFormat.BOTH,
) -> JSONResponse:
    extension = validate_upload(file)
    if extension != ".pdf":
        raise HTTPException(415, "This endpoint accepts PDF files only")
    upload_path = settings.upload_dir / f"{uuid.uuid4().hex}.pdf"
    try:
        await save_upload(file, upload_path, settings.max_file_size_bytes)
        try:
            page_count = await run_in_threadpool(
                inspect_pdf, upload_path, settings.max_pages
            )
        except (EncryptedPDFError, InvalidPDFError) as exc:
            raise HTTPException(400, str(exc)) from exc
        try:
            job = store.create_job(
                owner_id=owner_id,
                filename=file.filename or "document.pdf",
                output_format=output_format.value,
                total_pages=page_count,
                upload_path=upload_path,
            )
        except QueueFullError as exc:
            raise HTTPException(
                429, "PDF job queue is full", headers={"Retry-After": "60"}
            ) from exc
    except Exception:
        upload_path.unlink(missing_ok=True)
        raise
    return JSONResponse(_submission(job), status_code=202)


@router.get("/jobs/{job_id}")
def job_status(
    job_id: str,
    store: Annotated[JobStore, Depends(get_job_store)],
    owner_id: Annotated[str, Depends(get_owner_id)],
) -> dict[str, Any]:
    return _public_job(_owned_job(store, job_id, owner_id))


@router.get("/jobs/{job_id}/result/{artifact}")
def job_result(
    job_id: str,
    artifact: str,
    store: Annotated[JobStore, Depends(get_job_store)],
    owner_id: Annotated[str, Depends(get_owner_id)],
) -> FileResponse:
    if artifact not in {"json", "markdown"}:
        raise HTTPException(404, "Unknown result artifact")
    job = _owned_job(store, job_id, owner_id)
    if artifact not in _result_urls(job["id"], job["output_format"]):
        raise HTTPException(404, "Artifact was not requested")
    if job["status"] != "completed":
        raise HTTPException(409, f"Job is {job['status']}")
    path = Path(job["json_path"] if artifact == "json" else job["markdown_path"])
    if not path.is_file():
        raise HTTPException(409, "Result artifact is not ready")
    return FileResponse(
        path,
        media_type="application/json" if artifact == "json" else "text/markdown",
        filename=f"{job_id}.{'json' if artifact == 'json' else 'md'}",
    )


@router.delete("/jobs/{job_id}", status_code=202)
def cancel_job(
    job_id: str,
    store: Annotated[JobStore, Depends(get_job_store)],
    owner_id: Annotated[str, Depends(get_owner_id)],
) -> JSONResponse:
    job = store.cancel(job_id, owner_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return JSONResponse(_public_job(job), status_code=202)


def _owned_job(store: JobStore, job_id: str, owner_id: str) -> dict[str, Any]:
    job = store.get(job_id, owner_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


def _submission(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job["id"],
        "status": job["status"],
        "status_url": f"/jobs/{job['id']}",
        "result_urls": _result_urls(job["id"], job["output_format"]),
    }


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        **_submission(job),
        "filename": job["filename"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "completed_at": job["completed_at"],
        "total_pages": job["total_pages"],
        "pending_pages": job["pending_pages"],
        "running_pages": job["running_pages"],
        "completed_pages": job["completed_pages"],
        "failed_pages": job["failed_pages"],
        "cancellation_requested": job["cancellation_requested"],
        "retry_count": job["retry_count"],
        "error": job["error_summary"],
    }


def _result_urls(job_id: str, output_format: str) -> dict[str, str]:
    result: dict[str, str] = {}
    if output_format in {"json", "both"}:
        result["json"] = f"/jobs/{job_id}/result/json"
    if output_format in {"markdown", "both"}:
        result["markdown"] = f"/jobs/{job_id}/result/markdown"
    return result
