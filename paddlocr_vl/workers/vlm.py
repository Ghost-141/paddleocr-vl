from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import socket
from typing import Any

import httpx

from ..core.config import Settings, load_settings
from ..db.jobs import JobStore
from ..service import VllmClient, VllmError
from ..utils.markdown_assembler import assemble_page_markdown


async def process_one(
    store: JobStore,
    client: VllmClient,
    http_client: httpx.AsyncClient,
    task: dict[str, Any],
    worker_id: str,
) -> None:
    result_path = (
        store.settings.jobs_dir / task["job_id"] / "regions"
        / f"{task['page_number']:06d}-{task['region_number']:04d}.json"
    )
    try:
        result = await client.infer_async(http_client, Path(task["crop_path"]), label=task["label"])
        result_path.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        if store.finish_region(task, result_path):
            _merge_one(store, worker_id, task["job_id"], task["page_number"])
    except VllmError as exc:
        store.fail_region(task, str(exc), exc.transient)
    except Exception as exc:
        store.fail_region(task, str(exc), False)


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


def assemble_artifacts(job: dict[str, Any]) -> None:
    job_dir = Path(job["json_path"]).parent
    pages_dir = job_dir / "pages"
    want_json = job["output_format"] in {"json", "both"}
    want_markdown = job["output_format"] in {"markdown", "both"}
    json_file = Path(job["json_path"])
    markdown_file = Path(job["markdown_path"])
    json_tmp = json_file.with_suffix(".json.tmp")
    markdown_tmp = markdown_file.with_suffix(".md.tmp")
    previous_table_header: tuple[str, ...] | None = None

    json_output = json_tmp.open("w", encoding="utf-8") if want_json else None
    markdown_output = markdown_tmp.open("w", encoding="utf-8") if want_markdown else None
    try:
        if json_output:
            json_output.write(
                json.dumps({"job_id": job["id"], "filename": job["filename"]}, ensure_ascii=False)[:-1]
                + ',"pages":['
            )
        for page_number in range(1, job["total_pages"] + 1):
            page = json.loads((pages_dir / f"{page_number:06d}.json").read_text(encoding="utf-8"))
            previous_table_header = _normalize_cross_page(page, page_number, previous_table_header)
            if json_output:
                if page_number > 1:
                    json_output.write(",")
                json.dump({"page": page_number, "json": page}, json_output, ensure_ascii=False, separators=(",", ":"))
            if markdown_output:
                markdown = assemble_page_markdown(page)
                markdown_output.write(f"## Page {page_number}\n\n")
                if markdown:
                    markdown_output.write(markdown + "\n\n")
                markdown_output.write("---\n\n")
        if json_output:
            json_output.write("]}")
    finally:
        if json_output:
            json_output.close()
        if markdown_output:
            markdown_output.close()
    if want_json:
        json_tmp.replace(json_file)
    if want_markdown:
        markdown_tmp.replace(markdown_file)


def _normalize_cross_page(
    page: dict[str, Any], page_number: int, previous_table_header: tuple[str, ...] | None
) -> tuple[str, ...] | None:
    result = page.get("res") if isinstance(page.get("res"), dict) else page
    blocks = result.get("parsing_res_list")
    if not isinstance(blocks, list):
        return None
    for block in blocks:
        if page_number > 1 and isinstance(block, dict) and block.get("block_label") in {"doc_title", "document_title", "title"}:
            block["block_label"] = "section_title"
    first_table = next((block for block in blocks if isinstance(block, dict) and block.get("block_label") == "table"), None)
    if first_table:
        lines = str(first_table.get("block_content", "")).splitlines()
        header = tuple(lines[:2])
        if previous_table_header and header == previous_table_header:
            first_table["block_content"] = "\n".join(lines[2:])
    last = next((block for block in reversed(blocks) if isinstance(block, dict)), None)
    return tuple(str(last.get("block_content", "")).splitlines()[:2]) if last and last.get("block_label") == "table" else None


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


async def run(settings: Settings) -> None:
    store = JobStore(settings)
    client = VllmClient(settings)
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    concurrency = settings.vlm_dispatch_concurrency
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    in_flight: set[asyncio.Task[None]] = set()
    async with httpx.AsyncClient(limits=limits, timeout=httpx.Timeout(600)) as http_client:
        while True:
            capacity = concurrency - len(in_flight)
            if capacity:
                for task in store.claim_regions(worker_id, min(capacity, settings.vlm_claim_batch_size)):
                    in_flight.add(
                        asyncio.create_task(process_one(store, client, http_client, task, worker_id))
                    )
            if in_flight:
                done, in_flight = await asyncio.wait(
                    in_flight, timeout=0.02, return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    task.result()
                continue
            if not _merge_one(store, worker_id):
                await asyncio.sleep(0.02)


if __name__ == "__main__":
    argparse.ArgumentParser(description="VLM region consumer").parse_args()
    asyncio.run(run(load_settings()))
