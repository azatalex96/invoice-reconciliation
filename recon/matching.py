"""Match an invoice to its purchase order and receipt (domain rule 2).

Matching uses only the supplier ID and purchase-order ID printed on the
invoice. Amounts are never used: the seed data has two identical purchase
orders, so the closest-looking record could be the wrong one.
"""
from dataclasses import dataclass


@dataclass
class Match:
    purchase_order: dict | None = None
    receipt: dict | None = None
    problem: str | None = None  # set when the match is unresolved


def match_invoice(fields, reference):
    po_id = fields["po_id"]
    if po_id is None:
        return Match(problem="Missing reference: the invoice has no purchase-order reference.")

    po = reference.purchase_orders.get(po_id)
    if po is None:
        return Match(problem=f"Unknown reference: {po_id} is not in the purchase-order table.")
    if po["supplier_id"] != fields["supplier_id"]:
        return Match(problem=(
            f"Conflicting reference: {po_id} belongs to supplier {po['supplier_id']}, "
            f"but the invoice is from {fields['supplier_id']}."))
    if po["sku"] != fields["sku"]:
        return Match(problem=(
            f"Conflicting reference: {po_id} is for SKU {po['sku']}, "
            f"but the invoice bills {fields['sku']}."))

    receipts = [r for r in reference.receipts if r["po_id"] == po_id and r["sku"] == po["sku"]]
    if not receipts:
        return Match(purchase_order=po, problem=f"Missing receipt: no receipt recorded for {po_id}.")
    if len(receipts) > 1:
        ids = ", ".join(r["receipt_id"] for r in receipts)
        return Match(purchase_order=po, problem=f"Ambiguous receipt: more than one receipt for {po_id} ({ids}).")

    return Match(purchase_order=po, receipt=receipts[0])
