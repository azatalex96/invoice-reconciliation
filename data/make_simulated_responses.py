"""Write SIMULATED extraction responses, one per invoice image.

No model API key was available while building this submission, so these files
stand in for what a document-capable model would return. They are written from
the ground-truth invoice records, in the same raw-text JSON shape the live
provider asks the model for (amounts as printed on the image, e.g. "24.00").

Two responses are deliberately wrong so the app's failure paths are exercised:
- corrected-total: the total is misread as 98.00 instead of 90.00 (a reviewer
  corrects it in the app; see expected-reference-results.json).
- unreadable: the "model" declines to read the blurred image (invalid output).

Every file carries "source": "simulated" so it is never mistaken for a real call.
"""
import json
from pathlib import Path

root = Path(__file__).resolve().parent
out_dir = root / "model_responses" / "simulated"

MISREADS = {"corrected-total": {"total": "98.00"}}
REFUSALS = {"unreadable": "The image is too blurred to read the invoice fields reliably."}


def printed_fields(invoice):
    """The fields as they appear on the rendered image."""
    return {
        "invoice_number": invoice["invoice_number"],
        "supplier_id": invoice["supplier_id"],
        "po_id": invoice["po_id"],
        "sku": invoice["sku"],
        "quantity": invoice["quantity"],
        "unit_price": f"{invoice['unit_cents'] / 100:.2f}",
        "total": f"{invoice['total_cents'] / 100:.2f}",
    }


def main():
    invoices = []
    for name in ("seed/seed.json", "additions.json"):
        invoices += json.loads((root / name).read_text())["invoices"]

    out_dir.mkdir(parents=True, exist_ok=True)
    for invoice in invoices:
        file_id = invoice["file_id"]
        if file_id in REFUSALS:
            raw_text = REFUSALS[file_id]
        else:
            fields = printed_fields(invoice)
            fields.update(MISREADS.get(file_id, {}))
            raw_text = json.dumps(fields)
        response = {
            "source": "simulated",
            "model": None,
            "file_id": file_id,
            "raw_text": raw_text,
        }
        (out_dir / f"{file_id}.json").write_text(json.dumps(response, indent=2) + "\n")
        print("wrote", file_id)


if __name__ == "__main__":
    main()
