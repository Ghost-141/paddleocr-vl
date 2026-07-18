from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    vllm_url: str


class OutputFormat(str, Enum):
    JSON = "json"
    MARKDOWN = "markdown"
    BOTH = "both"
