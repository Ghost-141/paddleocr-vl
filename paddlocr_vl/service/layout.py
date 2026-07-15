from __future__ import annotations

import json
from pathlib import Path
import socket
from typing import Any
from urllib import error, request

from ..core.config import Settings
from .paddleocr_vl import TritonError


class LayoutClient:
    def __init__(self, settings: Settings) -> None:
        self.url = f"{settings.layout_url}/detect"

    def detect(self, image_path: Path, *, timeout: int = 120) -> list[dict[str, Any]]:
        body = json.dumps({"path": str(image_path)}).encode()
        try:
            with request.urlopen(
                request.Request(
                    self.url, data=body, headers={"Content-Type": "application/json"}
                ),
                timeout=timeout,
            ) as response:
                payload = json.load(response)
        except error.HTTPError as exc:
            raise TritonError(
                f"Layout returned HTTP {exc.code}: {exc.read().decode(errors='replace')[:500]}",
                transient=exc.code >= 500 or exc.code == 429,
            ) from exc
        except (error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise TritonError(f"Layout request failed: {exc}") from exc
        try:
            boxes = payload["res"]["boxes"]
            if not isinstance(boxes, list):
                raise TypeError("boxes is not a list")
            return [box for box in boxes if isinstance(box, dict)]
        except (KeyError, TypeError) as exc:
            raise TritonError(f"Invalid layout response: {exc}", transient=False) from exc
