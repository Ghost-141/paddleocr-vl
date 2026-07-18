from __future__ import annotations

from fastapi import FastAPI

from .api.router import api_router
from .core.config import Settings, load_settings
from .core.logger import configure_logging
from .db.jobs import JobStore

configure_logging()


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or load_settings()
    app = FastAPI(title="PaddleOCR-VL Document Parser API", version="2.0.0")
    app.state.settings = config
    app.state.job_store = JobStore(config)
    app.include_router(api_router)
    return app


app = create_app()
