"""Load the reference tables (purchase orders, receipts) and the document list."""
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ReferenceData:
    purchase_orders: dict  # po_id -> purchase order record
    receipts: list         # receipt records
    file_ids: list         # invoice documents, in arrival order


def load_reference_data(paths):
    """Merge one or more seed-shaped JSON files.

    Only the purchase orders, receipts and the invoice file IDs are used.
    The invoice field values in these files are ground truth for checking;
    the app gets its invoice values from extraction instead.
    """
    purchase_orders = {}
    receipts = []
    file_ids = []
    for path in paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for po in data["purchase_orders"]:
            purchase_orders[po["po_id"]] = po
        receipts += data["receipts"]
        file_ids += [invoice["file_id"] for invoice in data["invoices"]]
    return ReferenceData(purchase_orders, receipts, file_ids)
