"""Validation of raw model responses and of provider failures."""
import json
import unittest

from recon.extraction import ExtractionError, coerce_correction, parse_response, usd_to_cents
from recon.records import load_reference_data
from recon.workflow import process_batch
from tests.helpers import IMAGES_DIR, SEED_FILE

GOOD = {"invoice_number": "INV-2", "supplier_id": "S1", "po_id": "PO-2", "sku": "CAB-1",
        "quantity": 5, "unit_price": "24.00", "total": "120.00"}


class ParseResponseTest(unittest.TestCase):
    def test_valid_response(self):
        parsed = parse_response(json.dumps(GOOD))
        self.assertEqual(parsed["unit_cents"], 2400)
        self.assertEqual(parsed["total_cents"], 12000)

    def test_readable_true_is_accepted(self):
        self.assertEqual(parse_response(json.dumps({**GOOD, "readable": True}))["quantity"], 5)

    def test_fenced_json_and_missing_po(self):
        raw = "```json\n" + json.dumps({**GOOD, "po_id": "(missing)"}) + "\n```"
        self.assertIsNone(parse_response(raw)["po_id"])

    def test_invalid_responses_are_rejected(self):
        bad_responses = [
            "The image is too blurred.",
            json.dumps([GOOD]),
            json.dumps({**GOOD, "supplier_id": None}),
            json.dumps({**GOOD, "quantity": "five"}),
            json.dumps({**GOOD, "total": "120.005"}),  # never rounded
            json.dumps({**GOOD, "unit_price": "-1.00"}),
            json.dumps({**GOOD, "readable": False}),  # model says it cannot read the image
        ]
        for raw in bad_responses:
            with self.subTest(raw=raw):
                with self.assertRaises(ExtractionError):
                    parse_response(raw)

    def test_usd_to_cents(self):
        self.assertEqual(usd_to_cents("$1,234.50", "x"), 123450)
        self.assertEqual(usd_to_cents("20", "x"), 2000)

    def test_corrections_are_validated(self):
        self.assertEqual(coerce_correction("total_cents", " 9000 "), 9000)
        self.assertIsNone(coerce_correction("po_id", ""))
        for field, value in (("total_cents", "90.00"), ("quantity", "-1"), ("layout", "a")):
            with self.subTest(field=field):
                with self.assertRaises(ExtractionError):
                    coerce_correction(field, value)


class FailingProvider:
    """Simulates a model/API outage for one invoice."""

    def extract(self, file_id, image_path):
        if file_id == "wrong-price":
            raise TimeoutError("simulated API timeout")
        return {"source": "simulated", "model": None, "raw_text": json.dumps(
            {**GOOD, "invoice_number": file_id, "po_id": "PO-1", "unit_price": "20.00", "total": "100.00"})}

    def draft_note(self, prompt):
        raise ConnectionError("simulated API outage")


class ProviderFailureTest(unittest.TestCase):
    def test_api_failure_is_recorded_and_batch_continues(self):
        reference = load_reference_data([SEED_FILE])
        state = process_batch(reference, FailingProvider(), IMAGES_DIR)
        failed = state["invoices"]["wrong-price"]
        self.assertEqual(failed["result"]["status"], "failed")
        self.assertIn("simulated API timeout", failed["extraction"]["error"])
        self.assertEqual(state["invoices"]["clean"]["result"]["status"], "reconciled")
        # Note drafting fell back to the template instead of crashing.
        self.assertEqual(failed["note"]["source"], "template")


if __name__ == "__main__":
    unittest.main()
