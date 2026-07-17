import asyncio
import base64
import io
import json
from pathlib import Path
from urllib import request

import httpx

from paddlocr_vl.service import VllmClient


class FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def test_vllm_client_uses_openai_image_protocol(monkeypatch, settings_factory, tmp_path: Path) -> None:
    image = tmp_path / "page.jpg"
    image.write_bytes(b"jpeg")
    captured: dict[str, object] = {}
    raw = {"choices": [{"message": {"content": "Parsed text"}}]}

    def urlopen(req: request.Request, timeout: int):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data)
        captured["timeout"] = timeout
        return FakeResponse(json.dumps(raw).encode())

    monkeypatch.setattr(request, "urlopen", urlopen)
    result = VllmClient(settings_factory()).infer(image, label="text")

    body = captured["body"]
    image_url = body["messages"][0]["content"][0]["image_url"]["url"]  # type: ignore[index]
    assert base64.b64decode(image_url.split(",", 1)[1]) == b"jpeg"
    assert body["temperature"] == 0  # type: ignore[index]
    assert captured["url"] == "http://paddleocr-vlm-server:8118/v1/chat/completions"
    assert result == {"parsing_res_list": [{"block_label": "text", "block_content": "Parsed text"}]}


def test_vllm_client_reuses_an_async_client(settings_factory, tmp_path: Path) -> None:
    image = tmp_path / "page.jpg"
    image.write_bytes(b"jpeg")

    async def run() -> dict[str, object]:
        transport = httpx.MockTransport(
            lambda _: httpx.Response(200, json={"choices": [{"message": {"content": "Parsed text"}}]})
        )
        async with httpx.AsyncClient(transport=transport) as client:
            return await VllmClient(settings_factory()).infer_async(client, image, label="text")

    assert asyncio.run(run()) == {
        "parsing_res_list": [{"block_label": "text", "block_content": "Parsed text"}]
    }
