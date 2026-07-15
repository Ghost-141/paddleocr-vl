from __future__ import annotations

import base64
import json
from pathlib import Path
import socket
from typing import Any
from urllib import error, request

from ..core.config import Settings


class TritonError(RuntimeError):
    def __init__(self, message: str, *, transient: bool = True) -> None:
        super().__init__(message)
        self.transient = transient


class TritonClient:
    def __init__(self, settings: Settings) -> None:
        self.url = (
            f"{settings.triton_url}/v2/models/{settings.triton_model}/infer"
        )

    def infer(
        self, image_path: Path, *, use_layout_detection: bool = True, timeout: int = 600
    ) -> dict[str, Any]:
        pipeline_input = json.dumps(
            {
                "file": base64.b64encode(image_path.read_bytes()).decode("ascii"),
                "fileType": 1,
                "returnMarkdownImages": False,
                "visualize": False,
                "restructurePages": False,
                "useLayoutDetection": use_layout_detection,
            },
            separators=(",", ":"),
        )
        body = json.dumps(
            {
                "inputs": [
                    {
                        "name": "input",
                        "shape": [1, 1],
                        "datatype": "BYTES",
                        "data": [pipeline_input],
                    }
                ],
                "outputs": [{"name": "output"}],
            }
        ).encode()
        try:
            with request.urlopen(
                request.Request(
                    self.url,
                    data=body,
                    headers={"Content-Type": "application/json"},
                ),
                timeout=timeout,
            ) as response:
                raw = json.load(response)
        except error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:1000]
            raise TritonError(
                f"Triton returned HTTP {exc.code}: {detail}",
                transient=exc.code >= 500 or exc.code == 429,
            ) from exc
        except (error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise TritonError(f"Triton request failed: {exc}") from exc
        except (ValueError, TypeError) as exc:
            raise TritonError(f"Invalid Triton response: {exc}", transient=False) from exc

        try:
            output = json.loads(raw["outputs"][0]["data"][0])
            if output.get("errorCode", 0):
                raise TritonError(str(output.get("errorMsg", "pipeline error")))
            page = output["result"]["layoutParsingResults"][0]
            compact = page.get("prunedResult", page)
            if not isinstance(compact, dict):
                raise TypeError("page result is not an object")
            return _without_images(compact)
        except TritonError:
            raise
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise TritonError(f"Invalid pipeline response: {exc}", transient=False) from exc

    def ready(self, *, timeout: int = 3) -> bool:
        try:
            with request.urlopen(
                self.url.rsplit("/models/", 1)[0] + "/health/ready", timeout=timeout
            ) as response:
                return response.status == 200
        except OSError:
            return False


def _without_images(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_images(item)
            for key, item in value.items()
            if key not in {"outputImages", "inputImage", "images", "img"}
        }
    if isinstance(value, list):
        return [_without_images(item) for item in value]
    if isinstance(value, str) and value.startswith("data:image/"):
        return ""
    return value
