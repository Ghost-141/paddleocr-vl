from collections.abc import Callable
import json
from pathlib import Path
from typing import Any

import pytest

from paddlocr_vl.core.config import Settings
from paddlocr_vl.service.paddleocr_vl import PaddleOCRVLService


class FakeResult:
    def __init__(self, title: str) -> None:
        self.title = title

    def save_to_json(self, save_path: str) -> None:
        Path(save_path).write_text(
            json.dumps(
                {
                    "parsing_res_list": [
                        {
                            "block_label": "paragraph_title",
                            "block_content": self.title,
                            "block_bbox": [0, 0, 10, 10],
                            "block_order": 1,
                            "global_block_id": 1,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )


class FakePipeline:
    def __init__(self, results: list[FakeResult]) -> None:
        self.results = results
        self.restructure_calls: list[dict[str, bool]] = []

    def predict(self, _: str) -> list[FakeResult]:
        return self.results

    def restructure_pages(
        self,
        results: list[FakeResult],
        **options: bool,
    ) -> list[FakeResult]:
        self.restructure_calls.append(options)
        return results


def test_start_configures_paddleocr_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    settings = settings_factory()
    assert settings.layout_model_dir is not None
    settings.layout_model_dir.mkdir(parents=True)
    captured: dict[str, Any] = {}
    pipeline = FakePipeline([])

    def create_pipeline(**kwargs: Any) -> FakePipeline:
        captured.update(kwargs)
        return pipeline

    monkeypatch.setattr("paddlocr_vl.service.paddleocr_vl.PaddleOCRVL", create_pipeline)
    service = PaddleOCRVLService(settings)

    service.start()

    assert service.loaded is True
    assert captured["device"] == "cpu"
    assert captured["vl_rec_server_url"] == settings.vllm_server_url
    assert captured["layout_detection_model_dir"] == str(settings.layout_model_dir)
    service.stop()
    assert service.loaded is False


def test_start_rejects_missing_layout_model_directory(
    settings_factory: Callable[..., Settings],
) -> None:
    service = PaddleOCRVLService(settings_factory())

    with pytest.raises(RuntimeError, match="Layout model directory does not exist"):
        service.start()


def test_predict_saves_pages_assembles_markdown_and_restructures_pdf(
    settings_factory: Callable[..., Settings], tmp_path: Path
) -> None:
    settings = settings_factory(max_pages=2)
    pipeline = FakePipeline([FakeResult("# First"), FakeResult("# Second")])
    service = PaddleOCRVLService(settings)
    service._pipeline = pipeline  # Avoid loading the real provider in a unit test.
    input_path = tmp_path / "document.pdf"
    input_path.write_bytes(b"%PDF-test")

    result = service.predict(input_path, tmp_path / "result")

    assert result["processed_pages"] == 2
    assert result["combined_markdown"] == "# First\n\n# Second"
    assert result["pages"][0]["markdown"] == "# First"
    assert pipeline.restructure_calls == [
        {
            "merge_tables": True,
            "relevel_titles": True,
            "concatenate_pages": False,
        }
    ]
    assert (tmp_path / "result" / "page_1.json").is_file()
    assert (tmp_path / "result" / "page_1.md").read_text() == "# First\n"


def test_predict_requires_started_pipeline(
    settings_factory: Callable[..., Settings], tmp_path: Path
) -> None:
    service = PaddleOCRVLService(settings_factory())

    with pytest.raises(RuntimeError, match="pipeline is not initialized"):
        service.predict(tmp_path / "page.png", tmp_path / "result")
