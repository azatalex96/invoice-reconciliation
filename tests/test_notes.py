"""Model-written notes are checked before use; the cases come from the real Gemini run."""
import unittest

from recon.notes import check_model_note, draft_note
from tests.helpers import DATA, load_json

LIVE_RUN = load_json(DATA / "real-run" / "live-run-state.json")


class FakeNoteProvider:
    def __init__(self, text):
        self.text = text

    def draft_note(self, prompt):
        return self.text


def note_for(file_id, text):
    """Redraft a live-run invoice's note, with the model returning `text`."""
    invoice = LIVE_RUN["invoices"][file_id]
    return draft_note(file_id, invoice["fields"], invoice["result"], FakeNoteProvider(text))


def real_note(file_id):
    return LIVE_RUN["invoices"][file_id]["note"]["text"]


class ModelNoteCheckTest(unittest.TestCase):
    def test_real_duplicate_note_is_rejected(self):
        # Gemini wrote "No purchase order or receipt IDs are present", although
        # the invoice prints PO-1. The note must cite the printed reference.
        note = note_for("duplicate", real_note("duplicate"))
        self.assertEqual(note["source"], "template")
        self.assertIn("PO-1", note["rejected_model_note"]["reason"])
        self.assertEqual(note["rejected_model_note"]["text"], real_note("duplicate"))

    def test_real_grounded_notes_are_kept(self):
        for file_id in ("short-receipt", "conflicting-reference"):
            note = note_for(file_id, real_note(file_id))
            self.assertEqual(note["source"], "model", file_id)
            self.assertEqual(note["text"], real_note(file_id))

    def test_invented_id_is_rejected(self):
        text = real_note("short-receipt") + " See also PO-9."
        note = note_for("short-receipt", text)
        self.assertEqual(note["source"], "template")
        self.assertIn("PO-9", note["rejected_model_note"]["reason"])

    def test_invented_amount_is_rejected(self):
        text = real_note("short-receipt") + " The overcharge is 1250 cents."
        note = note_for("short-receipt", text)
        self.assertEqual(note["source"], "template")
        self.assertIn("1250", note["rejected_model_note"]["reason"])

    def test_no_model_text_uses_template(self):
        note = note_for("short-receipt", None)
        self.assertEqual(note["source"], "template")
        self.assertNotIn("rejected_model_note", note)


class WholeTokenTest(unittest.TestCase):
    """IDs and amounts must match exactly, not as fragments of longer ones."""

    FACTS = {"invoice_number": "INV-1", "po_id": "PO-1", "expected_cents": 10000}

    def test_longer_id_does_not_count_as_citing(self):
        self.assertIsNotNone(check_model_note("INV-1 was checked against PO-12.", self.FACTS))

    def test_fragment_of_an_amount_is_rejected(self):
        self.assertIsNotNone(check_model_note("INV-1 on PO-1 differs by 100 cents.", self.FACTS))

    def test_dollar_amount_is_rejected(self):
        reason = check_model_note("INV-1 on PO-1 should be $100.00.", self.FACTS)
        self.assertIn("dollars", reason)

    def test_exact_amount_with_thousands_separator_is_accepted(self):
        self.assertIsNone(check_model_note("INV-1 on PO-1: expected 10,000 cents.", self.FACTS))


if __name__ == "__main__":
    unittest.main()
