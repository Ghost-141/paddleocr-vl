from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Settings:
    public_api_key: str
    triton_url: str = "http://triton:8000"
    triton_model: str = "layout-parsing"
    layout_url: str = "http://layout:8090"
    data_dir: Path = Path("/data")
    max_file_size_mb: int = 100
    max_pages: int = 100
    max_jobs: int = 20
    max_pages_per_job: int = 3
    max_regions_per_page: int = 64
    lease_seconds: int = 900
    max_retries: int = 3
    retention_hours: int = 24

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def database_path(self) -> Path:
        return self.data_dir / "jobs.db"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"


def load_settings() -> Settings:
    load_dotenv(dotenv_path=Path.cwd() / ".env")
    api_key = os.getenv("PUBLIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("PUBLIC_API_KEY must be configured")
    settings = Settings(
        public_api_key=api_key,
        triton_url=os.getenv("TRITON_URL", "http://triton:8000").rstrip("/"),
        triton_model=os.getenv("TRITON_MODEL", "layout-parsing"),
        layout_url=os.getenv("LAYOUT_URL", "http://layout:8090").rstrip("/"),
        data_dir=Path(os.getenv("DATA_DIR", "/data")),
        max_file_size_mb=int(os.getenv("MAX_FILE_SIZE_MB", "100")),
        max_pages=int(os.getenv("MAX_PAGES", "100")),
        max_jobs=int(os.getenv("MAX_JOBS", "20")),
        max_pages_per_job=int(os.getenv("MAX_PAGES_PER_JOB", "3")),
        max_regions_per_page=int(os.getenv("MAX_REGIONS_PER_PAGE", "64")),
        lease_seconds=int(os.getenv("LEASE_SECONDS", "900")),
        max_retries=int(os.getenv("MAX_RETRIES", "3")),
        retention_hours=int(os.getenv("RETENTION_HOURS", "24")),
    )
    for name in (
        "max_file_size_mb",
        "max_pages",
        "max_jobs",
        "max_pages_per_job",
        "max_regions_per_page",
        "lease_seconds",
    ):
        if getattr(settings, name) < 1:
            raise RuntimeError(f"{name.upper()} must be at least 1")
    if settings.max_retries < 0 or settings.retention_hours < 1:
        raise RuntimeError("MAX_RETRIES must be non-negative and RETENTION_HOURS positive")
    return settings
