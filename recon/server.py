"""A small local web server for the review queue (standard library only).

Routes:
  GET  /                              review queue page
  GET  /api/state                     all invoices, summary and reference tables
  GET  /images/<file_id>.png          original invoice image
  POST /api/invoices/<id>/correct     {"field": ..., "value": ...}
  POST /api/invoices/<id>/review      {"status": "open"|"reviewed", "comment": ...}
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .extraction import ExtractionError
from .storage import save_state
from .workflow import apply_correction, set_review

STATIC_DIR = Path(__file__).parent / "static"


class ReviewApp:
    """Holds the state in memory and saves it after every change."""

    def __init__(self, state, state_path, reference, provider, images_dir):
        self.state = state
        self.state_path = state_path
        self.reference = reference
        self.provider = provider
        self.images_dir = Path(images_dir)
        self.lock = threading.Lock()

    def snapshot(self):
        with self.lock:
            return {**self.state,
                    "purchase_orders": self.reference.purchase_orders,
                    "receipts": self.reference.receipts}

    def correct(self, file_id, field, value):
        with self.lock:
            apply_correction(self.state, self.reference, self.provider, file_id, field, value)
            save_state(self.state_path, self.state)

    def review(self, file_id, status, comment):
        with self.lock:
            set_review(self.state, file_id, status, comment)
            save_state(self.state_path, self.state)


def make_server(app, port):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/":
                self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            elif self.path == "/api/state":
                self._send_json(200, app.snapshot())
            elif self.path.startswith("/images/"):
                name = Path(self.path).name  # .name drops any "../" in the path
                self._send_file(app.images_dir / name, "image/png")
            else:
                self._send_json(404, {"error": "not found"})

        def do_POST(self):
            parts = self.path.strip("/").split("/")  # api / invoices / <id> / <action>
            if len(parts) != 4 or parts[:2] != ["api", "invoices"]:
                return self._send_json(404, {"error": "not found"})
            file_id, action = parts[2], parts[3]
            if file_id not in app.state["invoices"]:
                return self._send_json(404, {"error": f"unknown invoice {file_id}"})
            body = self._read_json()
            try:
                if action == "correct":
                    app.correct(file_id, body.get("field"), body.get("value"))
                elif action == "review":
                    app.review(file_id, body.get("status"), body.get("comment", ""))
                else:
                    return self._send_json(404, {"error": "not found"})
            except (ExtractionError, ValueError) as error:
                return self._send_json(400, {"error": str(error)})
            self._send_json(200, app.snapshot())

        def _read_json(self):
            length = int(self.headers.get("Content-Length") or 0)
            try:
                return json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return {}

        def _send_json(self, code, data):
            self._send(code, json.dumps(data).encode("utf-8"), "application/json")

        def _send_file(self, path, content_type):
            if not path.is_file():
                return self._send_json(404, {"error": "not found"})
            self._send(200, path.read_bytes(), content_type)

        def _send(self, code, body, content_type):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass  # keep the console quiet

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
