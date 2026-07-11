from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_VLLM_SERVER_URL = "http://paddleocr-vlm-server:8118/v1"
DEFAULT_VLLM_MODEL_NAME = "PaddleOCR-VL-1.6-0.9B"
DEFAULT_DEVICE = "gpu:0"
DEFAULT_PIPELINE_VERSION = "v1.6"
DEFAULT_LAYOUT_MODEL_NAME = "PP-DocLayoutV2"
DEFAULT_LAYOUT_MODEL_DIR = Path("/models/PP-DocLayoutV2")
DEFAULT_FORMAT_BLOCK_CONTENT = True
DEFAULT_MERGE_LAYOUT_BLOCKS = True
DEFAULT_RESTRUCTURE_PAGES = True
DEFAULT_MERGE_CROSS_PAGE_TABLES = True
DEFAULT_RELEVEL_TITLES = True
DEFAULT_CONCATENATE_PAGES = False
DEFAULT_VL_REC_MAX_CONCURRENCY = 1
DEFAULT_UPLOAD_DIR = Path("/data/uploads")
DEFAULT_OUTPUT_DIR = Path("/data/outputs")
DEFAULT_MAX_FILE_SIZE_MB = 100
DEFAULT_MAX_PAGES = 100
DEFAULT_DELETE_TEMP_FILES = True


def _as_bool(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    public_api_key: str
    vllm_api_key: str
    vllm_server_url: str
    vllm_model_name: str
    device: str
    pipeline_version: str
    layout_model_name: str
    layout_model_dir: Path | None
    format_block_content: bool
    merge_layout_blocks: bool
    restructure_pages: bool
    merge_cross_page_tables: bool
    relevel_titles: bool
    concatenate_pages: bool
    vl_rec_max_concurrency: int
    upload_dir: Path
    output_dir: Path
    max_file_size_mb: int
    max_pages: int
    delete_temp_files: bool

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024


def load_settings() -> Settings:
    load_dotenv(dotenv_path=Path.cwd() / ".env")
    public_api_key = os.getenv("PUBLIC_API_KEY", "").strip()
    if not public_api_key:
        raise RuntimeError("PUBLIC_API_KEY must be configured")

    settings = Settings(
        public_api_key=public_api_key,
        vllm_api_key=os.getenv("VLLM_API_KEY", "EMPTY"),
        vllm_server_url=DEFAULT_VLLM_SERVER_URL,
        vllm_model_name=DEFAULT_VLLM_MODEL_NAME,
        device=os.getenv("DEVICE", DEFAULT_DEVICE).strip(),
        pipeline_version=DEFAULT_PIPELINE_VERSION,
        layout_model_name=DEFAULT_LAYOUT_MODEL_NAME,
        layout_model_dir=DEFAULT_LAYOUT_MODEL_DIR,
        format_block_content=DEFAULT_FORMAT_BLOCK_CONTENT,
        merge_layout_blocks=DEFAULT_MERGE_LAYOUT_BLOCKS,
        restructure_pages=DEFAULT_RESTRUCTURE_PAGES,
        merge_cross_page_tables=DEFAULT_MERGE_CROSS_PAGE_TABLES,
        relevel_titles=DEFAULT_RELEVEL_TITLES,
        concatenate_pages=DEFAULT_CONCATENATE_PAGES,
        vl_rec_max_concurrency=DEFAULT_VL_REC_MAX_CONCURRENCY,
        upload_dir=DEFAULT_UPLOAD_DIR,
        output_dir=DEFAULT_OUTPUT_DIR,
        max_file_size_mb=int(
            os.getenv("MAX_FILE_SIZE_MB", str(DEFAULT_MAX_FILE_SIZE_MB))
        ),
        max_pages=int(os.getenv("MAX_PAGES", str(DEFAULT_MAX_PAGES))),
        delete_temp_files=DEFAULT_DELETE_TEMP_FILES,
    )
    if settings.vl_rec_max_concurrency < 1:
        raise RuntimeError("VL_REC_MAX_CONCURRENCY must be at least 1")
    if settings.max_file_size_mb < 1:
        raise RuntimeError("MAX_FILE_SIZE_MB must be at least 1")
    if settings.max_pages < 1:
        raise RuntimeError("MAX_PAGES must be at least 1")
    return settings
