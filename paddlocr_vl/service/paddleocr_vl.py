from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import threading
from typing import Any

from paddleocr import PaddleOCRVL

from ..core.config import Settings
from ..utils.markdown_assembler import assemble_page_markdown


class PaddleOCRVLService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._inflight = threading.BoundedSemaphore(
            max(1, self.settings.vl_rec_max_concurrency)
        )
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

        with self._inflight:
            results = list(self._pipeline.predict(str(input_path)))
        # Semaphore released — GPU slot is free for the next request.
        # Everything below is CPU + disk I/O.

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

        page_markdowns: list[str] = [None] * len(results)  # type: ignore[list-item]
        page_jsons: list[dict[str, Any]] = [None] * len(results)  # type: ignore[list-item]

        def _process_page(index: int, result: Any) -> tuple[int, dict[str, Any], str]:
            json_path = output_dir / f"page_{index}.json"
            result.save_to_json(save_path=str(json_path))
            page_json = dict(result)
            page_markdown = assemble_page_markdown(page_json)
            markdown_path = output_dir / f"page_{index}.md"
            markdown_path.write_text(page_markdown + "\n", encoding="utf-8")
            return index, page_json, page_markdown

        max_workers = min(len(results), 8)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [
                pool.submit(_process_page, idx, res)
                for idx, res in enumerate(results, start=1)
            ]
            for future in as_completed(futures):
                idx, page_json, page_markdown = future.result()
                page_jsons[idx - 1] = page_json
                page_markdowns[idx - 1] = page_markdown

        pages = [
            {"page": i + 1, "json": page_jsons[i], "markdown": page_markdowns[i]}
            for i in range(len(results))
        ]

        combined = "\n\n".join(
            md for md in page_markdowns if md and md.strip()
        ).strip()

        return {
            "processed_pages": len(pages),
            "pages": pages,
            "combined_markdown": combined,
        }
