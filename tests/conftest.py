from collections.abc import Callable
from pathlib import Path

import pytest

from paddlocr_vl.core.config import Settings


@pytest.fixture
def settings_factory(tmp_path: Path) -> Callable[..., Settings]:
    def create(**overrides: object) -> Settings:
        values: dict[str, object] = {
            "public_api_key": "test-api-key",
            "vllm_url": "http://paddleocr-vlm-server:8118/v1",
            "data_dir": tmp_path / "data",
            "max_file_size_mb": 100,
            "max_pages": 100,
            "max_jobs": 20,
            "max_pages_per_job": 12,
            "lease_seconds": 900,
            "max_retries": 3,
        }
        values.update(overrides)
        return Settings(**values)  # type: ignore[arg-type]

    return create
