from __future__ import annotations

import hashlib
import secrets
from typing import Annotated

from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings
from ..db.jobs import JobStore

bearer_scheme = HTTPBearer(scheme_name="Bearer Authentication")


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_job_store(request: Request) -> JobStore:
    return request.app.state.job_store


def get_owner_id(request: Request) -> str:
    return request.state.owner_id


def authorize(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials, Security(bearer_scheme)],
) -> None:
    settings = get_settings(request)
    token = credentials.credentials.strip()
    if not secrets.compare_digest(token, settings.public_api_key):
        raise HTTPException(
            401,
            "Invalid public API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    request.state.owner_id = hashlib.sha256(token.encode()).hexdigest()
