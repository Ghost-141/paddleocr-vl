from __future__ import annotations

import argparse
import os
from pathlib import Path
import socket
import time
from typing import Any

from PIL import Image

from ..core.config import Settings, load_settings
from ..db.jobs import JobStore
from ..utils.pdf_utils import render_page
from ..service import LayoutClient, LayoutError


def process_one(store: JobStore, client: LayoutClient, worker_id: str) -> bool:
    task = store.claim(worker_id)
    if task is None:
        return False
    job_dir = store.settings.jobs_dir / task["job_id"]
    rendered = job_dir / f".{worker_id}-{task['page_number']}.jpg"
    try:
        render_page(Path(task["upload_path"]), task["page_number"], rendered)
        regions = _crop_regions(
            rendered,
            client.detect(rendered),
            job_dir / "regions",
            task["page_number"],
            store.settings.max_regions_per_page,
        )
        store.enqueue_regions(task, regions)
    except LayoutError as exc:
        store.fail_page(task, str(exc), exc.transient)
    except Exception as exc:
        store.fail_page(task, str(exc), False)
    finally:
        rendered.unlink(missing_ok=True)
    return True


def _crop_regions(
    image_path: Path,
    boxes: list[dict[str, Any]],
    directory: Path,
    page_number: int,
    maximum: int,
) -> list[dict[str, Any]]:
    directory.mkdir(parents=True, exist_ok=True)
    selected = sorted(boxes, key=_reading_order)[:maximum]
    with Image.open(image_path) as image:
        image = image.convert("RGB")
        width, height = image.size
        output: list[dict[str, Any]] = []
        for index, box in enumerate(selected, start=1):
            coordinate = box.get("coordinate")
            if not isinstance(coordinate, list) or len(coordinate) != 4:
                continue
            left, top, right, bottom = _clamp_box(coordinate, width, height)
            if right <= left or bottom <= top:
                continue
            destination = directory / f"{page_number:06d}-{index:04d}.jpg"
            image.crop((left, top, right, bottom)).save(destination, "JPEG", quality=90)
            output.append(
                {
                    "label": str(box.get("label", "text")),
                    "bbox": [left, top, right, bottom],
                    "crop_path": str(destination),
                }
            )
        if output:
            return output
        destination = directory / f"{page_number:06d}-0001.jpg"
        image.save(destination, "JPEG", quality=90)
        return [
            {
                "label": "text",
                "bbox": [0, 0, width, height],
                "crop_path": str(destination),
            }
        ]


def _clamp_box(
    coordinate: list[Any], width: int, height: int
) -> tuple[int, int, int, int]:
    left, top, right, bottom = (int(float(value)) for value in coordinate)
    return (
        max(0, left - 4),
        max(0, top - 4),
        min(width, right + 4),
        min(height, bottom + 4),
    )


def _reading_order(box: dict[str, Any]) -> float:
    value = box.get("order")
    return float(value) if isinstance(value, (int, float)) else 0.0


def run(settings: Settings) -> None:
    store = JobStore(settings)
    client = LayoutClient(settings)
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    while True:
        if not process_one(store, client, worker_id):
            time.sleep(0.1)


if __name__ == "__main__":
    argparse.ArgumentParser(description="Layout producer").parse_args()
    run(load_settings())
