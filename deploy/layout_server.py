"""Minimal PP-DocLayoutV3 HTTP producer; runs inside the official CPU PaddleX image."""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from paddlex import create_model


MODEL = create_model(
    model_name="PP-DocLayoutV3",
    model_dir=os.getenv("LAYOUT_MODEL_DIR", "/models/PP-DocLayoutV3"),
    device=os.getenv("LAYOUT_MODEL_DEVICE", "cpu"),
)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self._reply(200, {"status": "healthy"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/detect":
            self._reply(404, {"error": "not found"})
            return
        try:
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            path = Path(payload["path"])
            if not path.is_file() or not str(path).startswith("/data/"):
                raise ValueError("path must be a readable /data file")
            prediction = next(MODEL.predict(str(path), batch_size=1))
            self._reply(200, prediction.json)
        except Exception as exc:
            self._reply(422, {"error": str(exc)})

    def log_message(self, *_: object) -> None:
        return

    def _reply(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass


HTTPServer(("0.0.0.0", 8090), Handler).serve_forever()
