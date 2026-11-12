"""Reconcile a batch of extracted invoices (domain rules 2-4).

All amounts are integer USD cents. Statuses, in the order they are decided:
  failed      extraction gave no valid fields
  duplicate   same supplier ID + invoice number as an earlier invoice
  unresolved  no unambiguous purchase order and receipt
  discrepant  billed amount or quantity differs from the purchasing records
  reconciled  everything agrees
"""
from .matching import match_invoice

STATUSES = ["reconciled", "discrepant", "duplicate", "unresolved", "failed"]


def reconcile_batch(items, reference):
    """items: [{"file_id", "fields" (dict or None), "error" (str or None)}] in arrival order."""
    results = {}
    first_seen = {}  # (supplier_id, invoice_number) -> file_id
    for item in items:
        fields = item["fields"]
        if fields is None:
            results[item["file_id"]] = _result("failed", [f"Extraction failed: {item['error']}"])
            continue

        key = (fields["supplier_id"], fields["invoice_number"])
        if key in first_seen:
            original = first_seen[key]
            result = _result("duplicate", [
                f"Duplicate: same supplier ({key[0]}) and invoice number ({key[1]}) as {original}."])
            result["duplicate_of"] = original
            results[item["file_id"]] = result
            continue
        first_seen[key] = item["file_id"]

        results[item["file_id"]] = reconcile_invoice(fields, reference)
    return results


def reconcile_invoice(fields, reference):
    match = match_invoice(fields, reference)
    if match.problem:
        result = _result("unresolved", [match.problem])
        # Show the PO only if the reference itself was valid (e.g. receipt missing).
        if match.purchase_order:
            result["po_id"] = match.purchase_order["po_id"]
        return result

    po, receipt = match.purchase_order, match.receipt
    expected = po["quantity"] * po["unit_cents"]
    billed = fields["total_cents"]
    findings = _findings(fields, po, receipt, expected, billed)

    result = _result("discrepant" if findings else "reconciled", findings)
    result.update({
        "po_id": po["po_id"],
        "receipt_id": receipt["receipt_id"],
        "ordered_quantity": po["quantity"],
        "received_quantity": receipt["quantity"],
        "billed_quantity": fields["quantity"],
        "agreed_unit_cents": po["unit_cents"],
        "billed_unit_cents": fields["unit_cents"],
        "expected_cents": expected,
        "billed_cents": billed,
        "difference_cents": billed - expected,
        "count_as_payable": True,
    })
    return result


def _findings(fields, po, receipt, expected, billed):
    findings = []
    if fields["unit_cents"] != po["unit_cents"]:
        findings.append(
            f"Unit price: billed {fields['unit_cents']} cents, agreed {po['unit_cents']} cents on {po['po_id']}.")
    if fields["quantity"] != po["quantity"]:
        findings.append(
            f"Quantity: billed {fields['quantity']}, ordered {po['quantity']} on {po['po_id']}.")
    if fields["quantity"] != receipt["quantity"]:
        findings.append(
            f"Quantity: billed {fields['quantity']}, received {receipt['quantity']} on {receipt['receipt_id']}.")
    if fields["quantity"] * fields["unit_cents"] != billed:
        findings.append(
            f"Invoice arithmetic: {fields['quantity']} x {fields['unit_cents']} cents "
            f"= {fields['quantity'] * fields['unit_cents']}, but the invoice total is {billed}.")
    if billed != expected:
        findings.append(f"Amount: billed {billed} cents, expected {expected} cents.")
    return findings


def _result(status, findings):
    return {
        "status": status,
        "findings": findings,
        "po_id": None,
        "receipt_id": None,
        "expected_cents": None,
        "billed_cents": None,
        "difference_cents": None,
        "count_as_payable": False,
    }


def summarize(results):
    """Counts per status and the recoverable total.

    Only positive differences on matched, non-duplicate invoices (status
    "discrepant") are recoverable; duplicates and unresolved invoices are not.
    """
    counts = {status: 0 for status in STATUSES}
    recoverable = 0
    for result in results.values():
        counts[result["status"]] += 1
        if result["status"] == "discrepant" and result["difference_cents"] > 0:
            recoverable += result["difference_cents"]
    return {"counts": counts, "recoverable_cents": recoverable}
