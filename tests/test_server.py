"""End-to-end through HTTP: load queue, correct a field, restart, check it stuck."""
import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from recon.server import ReviewApp, make_server
from recon.storage import load_state, save_state
from tests.helpers import IMAGES_DIR, run_batch


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_path = Path(self.tmp.name) / "state.json"
        self.reference, self.provider, state = run_batch()
        save_state(self.state_path, state)
        self.start(state)

    def tearDown(self):
        self.stop()
        self.tmp.cleanup()

    def start(self, state):
        app = ReviewApp(state, self.state_path, self.reference, self.provider, IMAGES_DIR)
        self.server = make_server(app, 0)  # port 0: pick any free port
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as response:
            return response.read()

    def post(self, path, body):
        request = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST")
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read())

    def test_queue_page_image_and_state(self):
        self.assertIn(b"Invoice review queue", self.get("/"))
        self.assertTrue(self.get("/images/clean.png").startswith(b"\x89PNG"))
        state = json.loads(self.get("/api/state"))
        self.assertEqual(len(state["order"]), 8)
        self.assertIn("PO-1", state["purchase_orders"])

    def test_correction_and_review_persist_after_restart(self):
        self.post("/api/invoices/corrected-total/correct", {"field": "total_cents", "value": "9000"})
        self.post("/api/invoices/corrected-total/review", {"status": "reviewed", "comment": "misread total"})

        self.stop()
        self.start(load_state(self.state_path))  # restart from the saved file

        invoice = json.loads(self.get("/api/state"))["invoices"]["corrected-total"]
        self.assertEqual(invoice["result"]["status"], "reconciled")
        self.assertEqual(invoice["review"]["status"], "reviewed")
        self.assertEqual(invoice["extraction"]["fields"]["total_cents"], 9800)

    def test_bad_correction_is_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.post("/api/invoices/clean/correct", {"field": "total_cents", "value": "abc"})
        self.assertEqual(error.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
