from collections.abc import Callable
from pathlib import Path

import pytest

from paddlocr_vl.core.config import Settings


@pytest.fixture
def settings_factory(tmp_path: Path) -> Callable[..., Settings]:
    def create(**overrides: object) -> Settings:
        values: dict[str, object] = {
            "public_api_key": "test-api-key",
            "vllm_api_key": "EMPTY",
            "vllm_server_url": "http://paddleocr-vlm-server:8118/v1",
            "vllm_model_name": "PaddleOCR-VL-1.6-0.9B",
            "device": "cpu",
            "pipeline_version": "v1.6",
            "layout_model_name": "PP-DocLayoutV2",
            "layout_model_dir": tmp_path / "models" / "PP-DocLayoutV2",
            "format_block_content": True,
            "merge_layout_blocks": True,
            "restructure_pages": True,
            "merge_cross_page_tables": True,
            "relevel_titles": True,
            "concatenate_pages": False,
            "vl_rec_max_concurrency": 1,
            "upload_dir": tmp_path / "uploads",
            "output_dir": tmp_path / "outputs",
            "max_file_size_mb": 100,
            "max_pages": 100,
            "delete_temp_files": True,
        }
        values.update(overrides)
        return Settings(**values)  # type: ignore[arg-type]

    return create
