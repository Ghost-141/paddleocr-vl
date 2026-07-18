from collections.abc import Callable
from pathlib import Path

from PIL import Image

from paddlocr_vl.core.config import Settings
from paddlocr_vl.db.jobs import JobStore
from paddlocr_vl.workers.layout import _crop_regions, process_one


def test_crop_regions_accepts_layout_boxes_without_reading_order(tmp_path: Path) -> None:
    page = tmp_path / "page.jpg"
    Image.new("RGB", (100, 100)).save(page)

    regions = _crop_regions(
        page,
        [
            {"label": "text", "coordinate": [0, 0, 50, 20], "order": None},
            {"label": "table", "coordinate": [0, 30, 90, 90], "order": 1},
        ],
        tmp_path / "regions",
        1,
        64,
    )

    assert [region["label"] for region in regions] == ["text", "table"]


class FakeLayoutClient:
    def __init__(self) -> None:
        self.paths: list[Path] = []

    def detect(self, image_path: Path) -> list[dict[str, object]]:
        self.paths.append(image_path)
        return []


def test_image_job_uses_upload_without_pdf_render(
    settings_factory: Callable[..., Settings], tmp_path: Path, monkeypatch
) -> None:
    settings: Settings = settings_factory()
    store = JobStore(settings)
    image_path = tmp_path / "page.png"
    Image.new("RGB", (20, 20)).save(image_path)
    job = store.create_job(
        owner_id="owner",
        filename="page.png",
        output_format="both",
        total_pages=1,
        upload_path=image_path,
        source_type="image",
    )
    def render_must_not_run(*_: object) -> None:
        raise AssertionError("image must not be rendered")

    monkeypatch.setattr("paddlocr_vl.workers.layout.render_page", render_must_not_run)
    client = FakeLayoutClient()

    assert process_one(store, client, "layout") is True
    assert client.paths == [image_path]
    with store.connect() as db:
        assert db.execute(
            "SELECT status FROM pages WHERE job_id=?", (job["id"],)
        ).fetchone()[0] == "recognizing"
