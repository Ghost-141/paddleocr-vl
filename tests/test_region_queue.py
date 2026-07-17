from pathlib import Path

from paddlocr_vl.db.jobs import JobStore


def test_region_queue_finishes_a_page_only_after_its_regions(settings_factory, tmp_path: Path) -> None:
    settings = settings_factory()
    store = JobStore(settings)
    upload = tmp_path / "document.pdf"
    upload.write_bytes(b"pdf")
    job = store.create_job(
        owner_id="owner", filename="document.pdf", output_format="json", total_pages=1, upload_path=upload
    )
    page = store.claim("layout")
    assert page
    crop = tmp_path / "crop.jpg"
    crop.write_bytes(b"jpeg")
    store.enqueue_regions(page, [{"label": "text", "bbox": [0, 0, 10, 10], "crop_path": str(crop)}])

    region = store.claim_region("vlm")
    assert region and region["page_number"] == 1
    result = tmp_path / "region.json"
    result.write_text('{"parsing_res_list": []}')
    assert store.finish_region(region, result) is True
    merge = store.claim_page_merge("vlm", job["id"], 1)
    assert merge

    page_result = tmp_path / "page.json"
    page_result.write_text('{"parsing_res_list": []}')
    completed = store.complete_region_page(merge, page_result)
    assert completed["status"] == "completed"


def test_claim_regions_leases_a_batch(settings_factory, tmp_path: Path) -> None:
    store = JobStore(settings_factory())
    upload = tmp_path / "batch.pdf"
    upload.write_bytes(b"pdf")
    store.create_job(
        owner_id="owner", filename="batch.pdf", output_format="both", total_pages=1, upload_path=upload
    )
    page = store.claim("layout")
    assert page
    store.enqueue_regions(
        page,
        [
            {"label": "text", "bbox": [0, 0, 1, 1], "crop_path": str(tmp_path / f"{number}.jpg")}
            for number in range(3)
        ],
    )

    claimed = store.claim_regions("dispatcher", 2)

    assert len(claimed) == 2
    assert len({task["region_number"] for task in claimed}) == 2
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM regions WHERE status='running'").fetchone()[0] == 2
