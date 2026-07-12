from pathlib import Path

from paddlocr_vl.core.config import load_settings


def test_load_settings_defaults(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for name in (
        "PIPELINE_VERSION", "VLLM_SERVER_URL", "MAX_FILE_SIZE_MB",
        "VLLM_MODEL_NAME", "LAYOUT_MODEL_NAME", "VL_REC_MAX_CONCURRENCY",
        "MAX_PAGES", "DELETE_TEMP_FILES",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PUBLIC_API_KEY", "test-key")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))

    settings = load_settings()

    assert settings.pipeline_version == "v1.6"
    assert settings.vllm_server_url == "http://paddleocr-vlm-server:8118/v1"
    assert settings.max_file_size_bytes == 100 * 1024 * 1024
    assert settings.max_pages == 100
    assert settings.device == "gpu:0"


def test_load_settings_reads_runtime_overrides(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PUBLIC_API_KEY", "test-key")
    monkeypatch.setenv("DEVICE", "cpu")
    monkeypatch.setenv("MAX_FILE_SIZE_MB", "25")
    monkeypatch.setenv("MAX_PAGES", "12")

    settings = load_settings()

    assert settings.device == "cpu"
    assert settings.max_file_size_mb == 25
    assert settings.max_pages == 12


def test_load_settings_requires_public_api_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PUBLIC_API_KEY", raising=False)

    try:
        load_settings()
    except RuntimeError as exc:
        assert str(exc) == "PUBLIC_API_KEY must be configured"
    else:
        raise AssertionError("load_settings() accepted an empty API key")
