from collections.abc import Callable
from pathlib import Path
import time

from paddlocr_vl.core.config import Settings
from paddlocr_vl.db.jobs import JobStore


def make_job(store: JobStore, path: Path, name: str, pages: int = 2):
    path.write_bytes(b"pdf")
    return store.create_job(
        owner_id="owner",
        filename=name,
        output_format="both",
        total_pages=pages,
        upload_path=path,
    )


def test_atomic_claims_are_fair_and_limit_each_job_to_configured_depth(
    settings_factory: Callable[..., Settings], tmp_path: Path
) -> None:
    store = JobStore(settings_factory(max_pages_per_job=3))
    first = make_job(store, tmp_path / "a.pdf", "a.pdf", 3)
    second = make_job(store, tmp_path / "b.pdf", "b.pdf", 3)

    claim1 = store.claim("one")
    claim2 = store.claim("two")

    assert claim1 and claim1["job_id"] == first["id"]
    assert claim2 and claim2["job_id"] == second["id"]
    with store.connect() as db:
        db.execute("UPDATE jobs SET last_claimed_at=0 WHERE id=?", (first["id"],))
        db.execute("UPDATE jobs SET last_claimed_at=1 WHERE id=?", (second["id"],))
    assert store.claim("three")["job_id"] == first["id"]  # type: ignore[index]
    assert store.claim("four")["job_id"] == second["id"]  # type: ignore[index]
    assert store.claim("five")["job_id"] == first["id"]  # type: ignore[index]
    assert store.claim("six")["job_id"] == second["id"]  # type: ignore[index]
    assert store.claim("seven") is None


def test_expired_lease_is_reclaimed_and_transient_failure_retries(
    settings_factory: Callable[..., Settings], tmp_path: Path
) -> None:
    store = JobStore(settings_factory(lease_seconds=1, max_retries=3))
    job = make_job(store, tmp_path / "lease.pdf", "lease.pdf", 1)
    task = store.claim("crashed")
    assert task
    with store.connect() as db:
        db.execute(
            "UPDATE pages SET lease_expires=? WHERE job_id=?", (time.time() - 1, job["id"])
        )
    reclaimed = store.claim("replacement")
    assert reclaimed and reclaimed["attempts"] == 2

    store.fail_page(reclaimed, "temporarily unavailable", True)
    with store.connect() as db:
        db.execute("UPDATE pages SET available_at=0 WHERE job_id=?", (job["id"],))
    retried = store.claim("replacement")
    assert retried and retried["attempts"] == 3
    assert store.get(job["id"])["retry_count"] == 1  # type: ignore[index]


def test_cancellation_stops_pending_pages(
    settings_factory: Callable[..., Settings], tmp_path: Path
) -> None:
    store = JobStore(settings_factory())
    upload = tmp_path / "cancel.pdf"
    job = make_job(store, upload, "cancel.pdf", 2)
    running = store.claim("worker")
    cancelled = store.cancel(job["id"], "owner")
    assert cancelled and cancelled["cancellation_requested"] is True
    assert cancelled["pending_pages"] == 0
    assert store.claim("other") is None
    store.finish_page(running, tmp_path / "page.json")  # type: ignore[arg-type]
    assert store.get(job["id"])["status"] == "cancelled"  # type: ignore[index]
    assert upload.exists()
    assert store.get(job["id"]) is not None


def test_cancelled_expired_lease_does_not_leave_job_stuck(
    settings_factory: Callable[..., Settings], tmp_path: Path
) -> None:
    store = JobStore(settings_factory())
    job = make_job(store, tmp_path / "crash.pdf", "crash.pdf", 1)
    assert store.claim("crashed")
    store.cancel(job["id"], "owner")
    with store.connect() as db:
        db.execute("UPDATE pages SET lease_expires=0 WHERE job_id=?", (job["id"],))
    assert store.claim("replacement") is None
    assert store.get(job["id"])["status"] == "cancelled"  # type: ignore[index]
