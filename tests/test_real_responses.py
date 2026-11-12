"""Replay the saved REAL Gemini responses (no key, no network) against the expectations."""
import unittest

from recon.providers import SavedResponseProvider
from recon.records import load_reference_data
from recon.workflow import process_batch
from tests.helpers import ADDITIONS_FILE, DATA, IMAGES_DIR, SEED_FILE, load_json

LIVE_GEMINI = DATA / "model_responses" / "live-gemini"


class RealResponseReplayTest(unittest.TestCase):
    def setUp(self):
        reference = load_reference_data([SEED_FILE, ADDITIONS_FILE])
        self.state = process_batch(reference, SavedResponseProvider(LIVE_GEMINI), IMAGES_DIR)

    def test_responses_are_labelled_real(self):
        for invoice in self.state["invoices"].values():
            self.assertEqual(invoice["extraction"]["source"], "live")
            self.assertEqual(invoice["extraction"]["model"], "gemini-3.5-flash-lite")

    def test_seed_expectations_hold(self):
        for expected in load_json(DATA / "seed" / "expected-seed-results.json"):
            result = self.state["invoices"][expected["file_id"]]["result"]
            for key, value in expected.items():
                if key != "file_id":
                    self.assertEqual(result[key], value, (expected["file_id"], key))

    def test_batch_matches_corrected_expectations(self):
        # The real model read the 90.00 total correctly, so no correction is needed
        # and the batch already equals the hand-checked "after correction" summary.
        expected = load_json(DATA / "expected-reference-results.json")["expected_summary_after_correction"]
        self.assertEqual(self.state["summary"]["counts"], expected["counts"])
        self.assertEqual(self.state["summary"]["recoverable_cents"], expected["recoverable_cents"])

    def test_blurred_image_is_rejected_by_validation(self):
        invoice = self.state["invoices"]["unreadable"]
        self.assertEqual(invoice["result"]["status"], "failed")
        self.assertIn("invoice_number is missing", invoice["extraction"]["error"])


if __name__ == "__main__":
    unittest.main()
