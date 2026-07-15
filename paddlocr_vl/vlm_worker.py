from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import time
from typing import Any

from .core.config import Settings, load_settings
from .jobs import JobStore
from .service import TritonClient, TritonError
from .worker import assemble_artifacts


def process_one(store: JobStore, client: TritonClient, worker_id: str) -> bool:
    task = store.claim_region(worker_id)
    if task is None:
        return False
    result_path = (
        store.settings.jobs_dir / task["job_id"] / "regions"
        / f"{task['page_number']:06d}-{task['region_number']:04d}.json"
    )
    try:
        result = client.infer(Path(task["crop_path"]), use_layout_detection=False)
        result_path.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        if store.finish_region(task, result_path):
            _merge_one(store, worker_id, task["job_id"], task["page_number"])
    except TritonError as exc:
        store.fail_region(task, str(exc), exc.transient)
    except Exception as exc:
        store.fail_region(task, str(exc), False)
    return True


def _merge_page(store: JobStore, task: dict[str, Any]) -> Path:
    blocks: list[dict[str, Any]] = []
    for region in store.region_results(task["job_id"], task["page_number"]):
        result = json.loads(Path(region["result_path"]).read_text(encoding="utf-8"))
        source_blocks = result.get("parsing_res_list")
        if not isinstance(source_blocks, list):
            source_blocks = result.get("res", {}).get("parsing_res_list", [])
        content = "\n\n".join(
            str(block.get("block_content", ""))
            for block in source_blocks
            if isinstance(block, dict) and block.get("block_content")
        )
        if content:
            blocks.append(
                {
                    "block_label": region["label"],
                    "block_content": content,
                    "block_bbox": json.loads(region["bbox"]),
                }
            )
    page = {"parsing_res_list": blocks}
    path = store.settings.jobs_dir / task["job_id"] / "pages" / f"{task['page_number']:06d}.json"
    path.write_text(json.dumps(page, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return path


def _merge_one(
    store: JobStore, worker_id: str, job_id: str | None = None, page_number: int | None = None
) -> bool:
    task = store.claim_page_merge(worker_id, job_id, page_number)
    if task is None:
        return False
    try:
        page_path = _merge_page(store, task)
        job = store.complete_region_page(task, page_path)
        if job["status"] == "completed" and (claimed := store.claim_assembly(task["job_id"])):
            assemble_artifacts(claimed)
            store.complete_assembly(task["job_id"])
    except Exception as exc:
        store.fail_assembly(task["job_id"], f"Region merge failed: {exc}")
    return True


def run(settings: Settings) -> None:
    store = JobStore(settings)
    client = TritonClient(settings)
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    while True:
        if not process_one(store, client, worker_id) and not _merge_one(store, worker_id):
            time.sleep(0.02)


if __name__ == "__main__":
    argparse.ArgumentParser(description="VLM region consumer").parse_args()
    run(load_settings())
