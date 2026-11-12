"""The five reference cases and other additions, against hand-checked expectations.

Expected values live in data/expected-reference-results.json, written by hand
before the app was run; they are not copied from app output.
"""
import tempfile
import unittest
from pathlib import Path

from recon.storage import load_state, save_state
from recon.workflow import apply_correction
from tests.helpers import DATA, load_json, run_batch

EXPECTED = load_json(DATA / "expected-reference-results.json")
CASES = {case["file_id"]: case for case in EXPECTED["reference_cases"]}


class ReferenceCasesTest(unittest.TestCase):
    def setUp(self):
        self.reference, self.provider, self.state = run_batch()

    def assert_result(self, file_id, expected):
        result = self.state["invoices"][file_id]["result"]
        for key, value in expected.items():
            with self.subTest(file_id=file_id, key=key):
                self.assertEqual(result[key], value)

    def test_cases_1_to_4(self):
        for file_id in ("clean", "wrong-price", "duplicate", "missing-reference"):
            self.assert_result(file_id, CASES[file_id]["expected"])

    def test_other_cases(self):
        for case in EXPECTED["other_cases"]:
            self.assert_result(case["file_id"], case["expected"])

    def test_wrong_price_cites_invoice_and_agreed_price(self):
        invoice = self.state["invoices"]["wrong-price"]
        self.assertIn("agreed 2000 cents on PO-2", " ".join(invoice["result"]["findings"]))
        self.assertIn("INV-2", invoice["note"]["text"])
        self.assertIn("PO-2", invoice["note"]["text"])

    def test_summary_before_correction(self):
        expected = EXPECTED["expected_summary_before_correction"]
        self.assertEqual(self.state["summary"]["counts"], expected["counts"])
        self.assertEqual(self.state["summary"]["recoverable_cents"], expected["recoverable_cents"])

    def test_case_5_correction_reruns_and_survives_restart(self):
        case = CASES["corrected-total"]
        self.assert_result("corrected-total", case["expected_before_correction"])

        correction = case["correction"]
        apply_correction(self.state, self.reference, self.provider,
                         "corrected-total", correction["field"], str(correction["value"]))
        self.assert_result("corrected-total", case["expected_after_correction"])

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            save_state(path, self.state)
            reloaded = load_state(path)  # stands in for restarting the app

        invoice = reloaded["invoices"]["corrected-total"]
        for key, value in case["expected_after_correction"].items():
            self.assertEqual(invoice["result"][key], value)
        # The original extraction is kept so the correction can be understood.
        self.assertEqual(invoice["extraction"]["fields"]["total_cents"], 9800)
        self.assertEqual(invoice["corrections"][0]["old"], 9800)
        self.assertEqual(invoice["corrections"][0]["new"], 9000)

        expected = EXPECTED["expected_summary_after_correction"]
        self.assertEqual(reloaded["summary"]["counts"], expected["counts"])
        self.assertEqual(reloaded["summary"]["recoverable_cents"], expected["recoverable_cents"])


if __name__ == "__main__":
    unittest.main()
