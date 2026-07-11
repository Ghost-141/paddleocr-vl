from __future__ import annotations

from pathlib import Path
import threading
from typing import Any

from paddleocr import PaddleOCRVL

from ..core.config import Settings
from ..utils.file_utils import read_json
from ..utils.markdown_assembler import assemble_document_markdown, assemble_page_markdown


class PaddleOCRVLService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.Lock()
        self._pipeline: PaddleOCRVL | None = None

    @property
    def loaded(self) -> bool:
        return self._pipeline is not None

    def start(self) -> None:
        if (
            self.settings.layout_model_dir is not None
            and not self.settings.layout_model_dir.is_dir()
        ):
            raise RuntimeError(
                f"Layout model directory does not exist: "
                f"{self.settings.layout_model_dir}. Run the model setup step first."
            )
        self._pipeline = PaddleOCRVL(
            device=self.settings.device,
            pipeline_version=self.settings.pipeline_version,
            vl_rec_backend="vllm-server",
            vl_rec_server_url=self.settings.vllm_server_url,
            vl_rec_api_model_name=self.settings.vllm_model_name,
            vl_rec_api_key=self.settings.vllm_api_key,
            vl_rec_max_concurrency=self.settings.vl_rec_max_concurrency,
            layout_detection_model_name=self.settings.layout_model_name,
            layout_detection_model_dir=(
                str(self.settings.layout_model_dir)
                if self.settings.layout_model_dir is not None
                else None
            ),
            format_block_content=self.settings.format_block_content,
            merge_layout_blocks=self.settings.merge_layout_blocks,
        )

    def stop(self) -> None:
        self._pipeline = None

    def predict(self, input_path: Path, output_dir: Path) -> dict[str, Any]:
        if self._pipeline is None:
            raise RuntimeError("PaddleOCR-VL pipeline is not initialized")
        output_dir.mkdir(parents=True, exist_ok=True)
        pages: list[dict[str, Any]] = []
        document_pages: list[dict[str, Any]] = []
        with self._lock:
            results = list(self._pipeline.predict(str(input_path)))
            results = results[: self.settings.max_pages]
            if (
                input_path.suffix.lower() == ".pdf"
                and len(results) > 1
                and self.settings.restructure_pages
            ):
                restructure_pages = getattr(
                    self._pipeline, "restructure_pages", None
                )
                if not callable(restructure_pages):
                    raise RuntimeError(
                        "The installed PaddleOCR version does not support "
                        "multi-page restructuring"
                    )
                results = list(
                    restructure_pages(
                        results,
                        merge_tables=self.settings.merge_cross_page_tables,
                        relevel_titles=self.settings.relevel_titles,
                        concatenate_pages=self.settings.concatenate_pages,
                    )
                )

            for index, result in enumerate(results, start=1):
                json_path = output_dir / f"page_{index}.json"
                result.save_to_json(save_path=str(json_path))
                page_json = read_json(json_path)
                if not isinstance(page_json, dict):
                    raise RuntimeError("PaddleOCR-VL did not produce a valid JSON page result")
                page_markdown = assemble_page_markdown(page_json)
                markdown_path = output_dir / f"page_{index}.md"
                markdown_path.write_text(page_markdown + "\n", encoding="utf-8")
                page_entry = {"page": index, "json": page_json, "markdown": page_markdown}
                pages.append(page_entry)
                document_pages.append(page_json)
        return {
            "processed_pages": len(pages),
            "pages": pages,
            "combined_markdown": assemble_document_markdown(document_pages),
        }
