from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from paddlocr_vl.api.router import api_router
from paddlocr_vl.core.config import Settings


class FakeOCRService:
    def __init__(self, *, loaded: bool = True, error: Exception | None = None) -> None:
        self.loaded = loaded
        self.error = error
        self.calls: list[tuple[Path, Path]] = []

    def predict(self, input_path: Path, output_dir: Path) -> dict[str, Any]:
        self.calls.append((input_path, output_dir))
        assert input_path.is_file()
        if self.error is not None:
            raise self.error
        output_dir.mkdir(parents=True, exist_ok=True)
        return {
            "processed_pages": 1,
            "pages": [
                {
                    "page": 1,
                    "json": {"parsing_res_list": []},
                    "markdown": "Parsed text",
                }
            ],
            "combined_markdown": "Parsed text",
        }


def make_client(settings: Settings, service: FakeOCRService) -> TestClient:
    app = FastAPI()
    app.state.settings = settings
    app.state.ocr_service = service
    app.include_router(api_router)
    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-api-key"}


def test_health_reports_pipeline_state(
    settings_factory: Callable[..., Settings],
) -> None:
    settings = settings_factory()
    client = make_client(settings, FakeOCRService(loaded=False))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "starting",
        "pipeline_loaded": False,
        "vllm_server_url": settings.vllm_server_url,
        "vllm_model": settings.vllm_model_name,
        "layout_model": settings.layout_model_name,
    }


@pytest.mark.parametrize(
    ("headers", "status_code"),
    [({}, 401), ({"Authorization": "Bearer wrong-key"}, 401)],
)
def test_parse_requires_valid_bearer_token(
    settings_factory: Callable[..., Settings],
    headers: dict[str, str],
    status_code: int,
) -> None:
    client = make_client(settings_factory(), FakeOCRService())

    response = client.post(
        "/parse/image",
        headers=headers,
        files={"file": ("page.png", b"image", "image/png")},
    )

    assert response.status_code == status_code


def test_parse_image_returns_both_formats_and_cleans_temp_files(
    settings_factory: Callable[..., Settings], auth_headers: dict[str, str]
) -> None:
    settings = settings_factory()
    service = FakeOCRService()
    client = make_client(settings, service)

    response = client.post(
        "/parse/image",
        headers=auth_headers,
        files={"file": ("page.png", b"image-bytes", "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "page.png"
    assert body["content_type"] == "image/png"
    assert body["file_size_bytes"] == len(b"image-bytes")
    assert body["processed_pages"] == 1
    assert body["pages"][0]["markdown"] == "Parsed text"
    assert body["combined_markdown"] == "Parsed text"
    upload_path, output_dir = service.calls[0]
    assert not upload_path.exists()
    assert not output_dir.exists()


@pytest.mark.parametrize(
    ("output_format", "has_pages", "has_markdown"),
    [("json", True, False), ("markdown", False, True), ("both", True, True)],
)
def test_parse_pdf_output_formats(
    settings_factory: Callable[..., Settings],
    auth_headers: dict[str, str],
    output_format: str,
    has_pages: bool,
    has_markdown: bool,
) -> None:
    client = make_client(settings_factory(), FakeOCRService())

    response = client.post(
        f"/parse/pdf?output_format={output_format}",
        headers=auth_headers,
        files={"file": ("document.pdf", b"%PDF-test", "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert ("pages" in body) is has_pages
    assert ("combined_markdown" in body) is has_markdown
    if output_format == "json":
        assert "markdown" not in body["pages"][0]


@pytest.mark.parametrize(
    ("endpoint", "filename", "content_type"),
    [
        ("/parse/image", "document.pdf", "application/pdf"),
        ("/parse/pdf", "page.png", "image/png"),
        ("/parse/image", "page.gif", "image/gif"),
    ],
)
def test_parse_rejects_wrong_file_type(
    settings_factory: Callable[..., Settings],
    auth_headers: dict[str, str],
    endpoint: str,
    filename: str,
    content_type: str,
) -> None:
    client = make_client(settings_factory(), FakeOCRService())

    response = client.post(
        endpoint,
        headers=auth_headers,
        files={"file": (filename, b"content", content_type)},
    )

    assert response.status_code == 415


def test_parse_rejects_oversized_upload_and_removes_partial_file(
    settings_factory: Callable[..., Settings], auth_headers: dict[str, str]
) -> None:
    settings = settings_factory(max_file_size_mb=1)
    service = FakeOCRService()
    client = make_client(settings, service)

    response = client.post(
        "/parse/image",
        headers=auth_headers,
        files={"file": ("large.png", b"x" * (1024 * 1024 + 1), "image/png")},
    )

    assert response.status_code == 413
    assert service.calls == []
    assert not list(settings.upload_dir.glob("*"))


def test_parse_maps_service_failure_to_bad_gateway_and_cleans_up(
    settings_factory: Callable[..., Settings], auth_headers: dict[str, str]
) -> None:
    settings = settings_factory()
    service = FakeOCRService(error=RuntimeError("backend unavailable"))
    client = make_client(settings, service)

    response = client.post(
        "/parse/pdf",
        headers=auth_headers,
        files={"file": ("document.pdf", b"%PDF-test", "application/pdf")},
    )

    assert response.status_code == 502
    assert "backend unavailable" in response.json()["detail"]
    upload_path, output_dir = service.calls[0]
    assert not upload_path.exists()
    assert not output_dir.exists()
