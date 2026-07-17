from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
import socket
from typing import Any
from urllib import error, request

import httpx

from ..core.config import Settings


class VllmError(RuntimeError):
    def __init__(self, message: str, *, transient: bool = True) -> None:
        super().__init__(message)
        self.transient = transient


class VllmClient:
    """Stateless OpenAI-compatible client for the single shared vLLM server."""

    def __init__(self, settings: Settings) -> None:
        self.url = f"{settings.vllm_url}/chat/completions"
        self.model = settings.vllm_model

    def infer(self, image_path: Path, *, label: str = "document", timeout: int = 600) -> dict[str, Any]:
        payload = self._payload(image_path, label)
        try:
            with request.urlopen(
                request.Request(
                    self.url,
                    data=json.dumps(payload, separators=(",", ":")).encode(),
                    headers={"Content-Type": "application/json"},
                ),
                timeout=timeout,
            ) as response:
                raw = json.load(response)
        except error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:1000]
            raise VllmError(
                f"vLLM returned HTTP {exc.code}: {detail}", transient=exc.code >= 500 or exc.code == 429
            ) from exc
        except (error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise VllmError(f"vLLM request failed: {exc}") from exc
        return self._result(raw, label)

    async def infer_async(
        self, client: httpx.AsyncClient, image_path: Path, *, label: str = "document"
    ) -> dict[str, Any]:
        payload = await asyncio.to_thread(self._payload, image_path, label)
        try:
            response = await client.post(self.url, json=payload)
            response.raise_for_status()
            raw = response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:1000]
            raise VllmError(
                f"vLLM returned HTTP {exc.response.status_code}: {detail}",
                transient=exc.response.status_code >= 500 or exc.response.status_code == 429,
            ) from exc
        except httpx.HTTPError as exc:
            raise VllmError(f"vLLM request failed: {exc}") from exc
        return self._result(raw, label)

    def _payload(self, image_path: Path, label: str) -> dict[str, Any]:
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        return {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
                        {
                            "type": "text",
                            "text": f"Extract the {label} content. Return only the result in Markdown, with no explanation.",
                        },
                    ],
                }
            ],
            "temperature": 0,
        }

    @staticmethod
    def _result(raw: dict[str, Any], label: str) -> dict[str, Any]:
        try:
            content = raw["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("message content is not text")
            return {"parsing_res_list": [{"block_label": label, "block_content": content}]}
        except (KeyError, IndexError, TypeError) as exc:
            raise VllmError(f"Invalid vLLM response: {exc}", transient=False) from exc

    def ready(self, *, timeout: int = 3) -> bool:
        try:
            with request.urlopen(self.url.rsplit("/v1/", 1)[0] + "/health", timeout=timeout) as response:
                return response.status == 200
        except OSError:
            return False
