from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from paddlocr_vl.api.router import api_router
from paddlocr_vl.core.config import Settings
from paddlocr_vl.db.jobs import JobStore


def make_client(settings: Settings) -> TestClient:
    app = FastAPI()
    app.state.settings = settings
    app.state.job_store = JobStore(settings)
    app.include_router(api_router)
    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-api-key"}


def test_health_reports_gateway_state(settings_factory: Callable[..., Settings]) -> None:
    response = make_client(settings_factory()).get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "vllm_url": "http://paddleocr-vlm-server:8118/v1",
    }


@pytest.mark.parametrize("endpoint", ["/parse/image", "/jobs/unknown"])
def test_protected_endpoints_require_bearer_token(
    settings_factory: Callable[..., Settings], endpoint: str
) -> None:
    client = make_client(settings_factory())
    response = (
        client.post(endpoint, files={"file": ("page.png", b"image", "image/png")})
        if endpoint.startswith("/parse")
        else client.get(endpoint)
    )
    assert response.status_code == 401


@pytest.mark.parametrize("output_format", ["json", "markdown", "both"])
def test_parse_image_creates_durable_job(
    settings_factory: Callable[..., Settings],
    auth_headers: dict[str, str],
    output_format: str,
) -> None:
    settings = settings_factory()
    response = make_client(settings).post(
        f"/parse/image?output_format={output_format}",
        headers=auth_headers,
        files={"file": ("page.png", b"image-bytes", "image/png")},
    )
    assert response.status_code == 202
    body = response.json()
    assert set(body["result_urls"]) == (
        {"json", "markdown"} if output_format == "both" else {output_format}
    )
    job = JobStore(settings).get(body["job_id"])
    assert job and job["total_pages"] == 1 and job["source_type"] == "image"
    assert Path(job["upload_path"]).is_file()


@pytest.mark.parametrize("output_format", ["json", "markdown", "both"])
def test_parse_pdf_creates_durable_job_and_result_urls(
    settings_factory: Callable[..., Settings],
    auth_headers: dict[str, str],
    output_format: str,
) -> None:
    response = make_client(settings_factory()).post(
        f"/parse/pdf?output_format={output_format}",
        headers=auth_headers,
        files={"file": ("document.pdf", Path("test.pdf").read_bytes(), "application/pdf")},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["status_url"] == f"/jobs/{body['job_id']}"
    assert set(body["result_urls"]) == (
        {"json", "markdown"} if output_format == "both" else {output_format}
    )


def test_status_result_and_cancel_are_authenticated(
    settings_factory: Callable[..., Settings], auth_headers: dict[str, str]
) -> None:
    settings = settings_factory()
    client = make_client(settings)
    submitted = client.post(
        "/parse/pdf?output_format=markdown",
        headers=auth_headers,
        files={"file": ("document.pdf", Path("test.pdf").read_bytes(), "application/pdf")},
    ).json()
    job_id = submitted["job_id"]
    assert client.get(f"/jobs/{job_id}", headers=auth_headers).json()["total_pages"] == 3
    incomplete = client.get(f"/jobs/{job_id}/result/markdown", headers=auth_headers)
    assert incomplete.status_code == 409
    cancelled = client.delete(f"/jobs/{job_id}", headers=auth_headers)
    assert cancelled.status_code == 202
    assert cancelled.json()["status"] == "cancelled"


def test_completed_result_is_raw_file(
    settings_factory: Callable[..., Settings], auth_headers: dict[str, str]
) -> None:
    settings = settings_factory()
    store = JobStore(settings)
    upload = settings.upload_dir / "done.pdf"
    upload.write_bytes(b"pdf")
    job = store.create_job(
        owner_id=__import__("hashlib").sha256(b"test-api-key").hexdigest(),
        filename="done.pdf",
        output_format="markdown",
        total_pages=1,
        upload_path=upload,
    )
    Path(job["markdown_path"]).write_text("# Done\n")
    with store.connect() as db:
        db.execute("UPDATE jobs SET status='completed' WHERE id=?", (job["id"],))
    app = FastAPI()
    app.state.settings = settings
    app.state.job_store = store
    app.include_router(api_router)
    response = TestClient(app).get(
        f"/jobs/{job['id']}/result/markdown", headers=auth_headers
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.text == "# Done\n"


def test_pdf_rejects_corrupt_over_limit_oversize_and_full_queue(
    settings_factory: Callable[..., Settings], auth_headers: dict[str, str]
) -> None:
    corrupt = make_client(settings_factory()).post(
        "/parse/pdf",
        headers=auth_headers,
        files={"file": ("bad.pdf", b"%PDF-bad", "application/pdf")},
    )
    assert corrupt.status_code == 400

    over_pages = make_client(settings_factory(max_pages=2)).post(
        "/parse/pdf",
        headers=auth_headers,
        files={"file": ("long.pdf", Path("test.pdf").read_bytes(), "application/pdf")},
    )
    assert over_pages.status_code == 400

    oversized = make_client(settings_factory(max_file_size_mb=1)).post(
        "/parse/pdf",
        headers=auth_headers,
        files={"file": ("big.pdf", b"x" * (1024 * 1024 + 1), "application/pdf")},
    )
    assert oversized.status_code == 413

    client = make_client(settings_factory(max_jobs=1))
    payload = {"file": ("doc.pdf", Path("test.pdf").read_bytes(), "application/pdf")}
    assert client.post("/parse/pdf", headers=auth_headers, files=payload).status_code == 202
    full = client.post("/parse/pdf", headers=auth_headers, files=payload)
    assert full.status_code == 429
    assert full.headers["retry-after"] == "60"
