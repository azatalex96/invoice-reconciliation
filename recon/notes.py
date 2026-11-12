"""Draft review notes and a short batch insight.

Notes are always drafts. They are built only from findings that code has
already checked. With a live model the provider rewrites the same facts as a
short note; otherwise a plain template is used. The note records its source.
"""
import json
from collections import Counter

NOTE_PROMPT = """Write a short, neutral draft note (at most 4 sentences) for an accounts-payable reviewer.
Use only the verified facts below. Cite the invoice number, purchase order and receipt IDs given.
Do not add amounts or claims that are not in the facts, and do not suggest wrongdoing.
Amounts are in USD cents.

Facts:
{facts}"""


def draft_note(file_id, fields, result, provider):
    if result["status"] == "reconciled":
        return {"source": "none", "text": ""}
    facts = _facts(file_id, fields, result)
    try:
        text = provider.draft_note(NOTE_PROMPT.format(facts=json.dumps(facts, indent=2)))
    except Exception as error:  # a note failure must not stop the batch
        text = None
        facts["note_error"] = str(error)
    if text:
        return {"source": "model", "text": text}
    return {"source": "template", "text": _template_note(facts)}


def _facts(file_id, fields, result):
    facts = {"file_id": file_id, "status": result["status"], "findings": result["findings"]}
    if fields:
        facts["invoice_number"] = fields["invoice_number"]
        facts["supplier_id"] = fields["supplier_id"]
    for key in ("po_id", "receipt_id", "expected_cents", "billed_cents", "difference_cents", "duplicate_of"):
        if result.get(key) is not None:
            facts[key] = result[key]
    return facts


def _template_note(facts):
    invoice = facts.get("invoice_number", facts["file_id"])
    lines = [f"DRAFT - {invoice} ({facts['file_id']}) is {facts['status']}."]
    lines += facts["findings"]
    if facts["status"] == "discrepant":
        lines.append(
            f"Checked against {facts['po_id']} and {facts['receipt_id']}; "
            f"difference (billed minus expected) {facts['difference_cents']} cents.")
    if facts["status"] == "unresolved":
        lines.append("No expected amount is given until the reference is confirmed.")
    if facts["status"] == "duplicate":
        lines.append("Not counted as a separate payable invoice.")
    return " ".join(lines)


def batch_insight(results):
    """One sentence on the most common finding type, taken from the results."""
    kinds = Counter()
    for result in results.values():
        # Findings start with their kind, e.g. "Quantity: ..." or "Conflicting reference: ..."
        for kind in {finding.split(":")[0] for finding in result["findings"]}:
            kinds[kind] += 1
    if not kinds:
        return "No findings in this batch."
    caveat = " These are review prompts, not proof of error or wrongdoing."
    kind, count = kinds.most_common(1)[0]
    if count == 1:
        return "No finding type recurs in this batch; each appears once: " + ", ".join(kinds) + "." + caveat
    others = ", ".join(f"{k} ({n})" for k, n in kinds.most_common()[1:])
    text = f"Recurring finding: {kind} on {count} invoices."
    if others:
        text += f" Others: {others}."
    return text + caveat
