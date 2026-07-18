from pathlib import Path

from paddlocr_vl.core.config import load_settings


def test_load_settings_defaults(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PUBLIC_API_KEY", "test-key")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))

    settings = load_settings()

    assert settings.vllm_url == "http://paddleocr-vlm-server:8118/v1"
    assert settings.max_file_size_bytes == 100 * 1024 * 1024
    assert settings.max_pages == 100
    assert settings.max_jobs == 20
    assert settings.max_pages_per_job == 3


def test_load_settings_reads_runtime_overrides(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PUBLIC_API_KEY", "test-key")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("VLLM_URL", "http://pipeline:9000/v1/")
    monkeypatch.setenv("MAX_FILE_SIZE_MB", "25")
    monkeypatch.setenv("MAX_PAGES", "12")
    monkeypatch.setenv("MAX_PAGES_PER_JOB", "4")

    settings = load_settings()

    assert settings.data_dir == tmp_path / "runtime"
    assert settings.vllm_url == "http://pipeline:9000/v1"
    assert settings.max_file_size_mb == 25
    assert settings.max_pages == 12
    assert settings.max_pages_per_job == 4


def test_load_settings_requires_public_api_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PUBLIC_API_KEY", raising=False)

    try:
        load_settings()
    except RuntimeError as exc:
        assert str(exc) == "PUBLIC_API_KEY must be configured"
    else:
        raise AssertionError("load_settings() accepted an empty API key")
