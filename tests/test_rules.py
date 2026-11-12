"""Unit checks for matching, reconciliation, duplicates and totals."""
import unittest

from recon.reconcile import reconcile_batch, reconcile_invoice, summarize
from recon.records import load_reference_data
from tests.helpers import ADDITIONS_FILE, SEED_FILE, fields

REFERENCE = load_reference_data([SEED_FILE, ADDITIONS_FILE])


class MatchingTest(unittest.TestCase):
    def test_matches_by_po_id_not_amount(self):
        # PO-1 and PO-2 are identical apart from their IDs.
        self.assertEqual(reconcile_invoice(fields(po_id="PO-2"), REFERENCE)["po_id"], "PO-2")
        self.assertEqual(reconcile_invoice(fields(po_id="PO-1"), REFERENCE)["po_id"], "PO-1")

    def test_missing_unknown_and_conflicting_references_are_unresolved(self):
        for bad in (fields(po_id=None), fields(po_id="PO-99"),
                    fields(supplier_id="S2"), fields(sku="HUB-2")):
            with self.subTest(fields=bad):
                result = reconcile_invoice(bad, REFERENCE)
                self.assertEqual(result["status"], "unresolved")
                self.assertIsNone(result["expected_cents"])
                self.assertIsNone(result["difference_cents"])

    def test_quantity_compared_with_ordered_and_received(self):
        result = reconcile_invoice(fields(quantity=6, total_cents=12000), REFERENCE)
        self.assertEqual(result["status"], "discrepant")
        self.assertEqual(result["expected_cents"], 10000)  # ordered qty x agreed price
        self.assertEqual(result["difference_cents"], 2000)
        text = " ".join(result["findings"])
        self.assertIn("ordered 5", text)
        self.assertIn("received 5", text)

    def test_undercharge_is_negative_and_not_recoverable(self):
        results = {"x": reconcile_invoice(fields(unit_cents=1500, total_cents=7500), REFERENCE)}
        self.assertEqual(results["x"]["difference_cents"], -2500)
        self.assertEqual(summarize(results)["recoverable_cents"], 0)


class DuplicateTest(unittest.TestCase):
    def test_first_occurrence_kept_later_one_flagged(self):
        items = [{"file_id": "a", "fields": fields(), "error": None},
                 {"file_id": "b", "fields": fields(unit_cents=2400, total_cents=12000), "error": None}]
        results = reconcile_batch(items, REFERENCE)
        self.assertEqual(results["a"]["status"], "reconciled")
        self.assertEqual(results["b"]["status"], "duplicate")
        self.assertEqual(results["b"]["duplicate_of"], "a")
        # The duplicate's overcharge must not be counted as recoverable.
        self.assertEqual(summarize(results)["recoverable_cents"], 0)

    def test_same_number_different_supplier_is_not_duplicate(self):
        items = [{"file_id": "a", "fields": fields(), "error": None},
                 {"file_id": "b", "fields": fields(supplier_id="S2", po_id="PO-3", sku="ADP-7",
                                                   quantity=4, unit_cents=1250, total_cents=5000),
                  "error": None}]
        self.assertNotEqual(reconcile_batch(items, REFERENCE)["b"]["status"], "duplicate")

    def test_failed_extraction_does_not_stop_batch(self):
        items = [{"file_id": "bad", "fields": None, "error": "provider error: timeout"},
                 {"file_id": "good", "fields": fields(), "error": None}]
        results = reconcile_batch(items, REFERENCE)
        self.assertEqual(results["bad"]["status"], "failed")
        self.assertEqual(results["good"]["status"], "reconciled")


if __name__ == "__main__":
    unittest.main()
