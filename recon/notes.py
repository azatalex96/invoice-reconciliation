"""Draft review notes and a short batch insight.

Notes are always drafts. They are built only from findings that code has
already checked. With a live model the provider rewrites the same facts as a
short note, and check_model_note() rejects a note that leaves out a cited ID or
mentions an ID or amount that is not in the facts. A rejected note (or no
model) falls back to a plain template. The note records its source.
"""
import json
import re
from collections import Counter

NOTE_PROMPT = """Write a short, neutral draft note (at most 4 sentences) for an accounts-payable reviewer.
Use only the verified facts below. Cite the invoice number, purchase order and receipt IDs given.
Do not add amounts or claims that are not in the facts, do not say that information is missing
unless the facts say so, and do not suggest wrongdoing. Amounts are in USD cents.

Facts:
{facts}"""

# Facts whose IDs a note must cite. invoice_po_reference is the PO printed on
# the invoice, given even when no match was made (e.g. duplicates).
REQUIRED_ID_KEYS = ("invoice_number", "invoice_po_reference", "po_id", "receipt_id")
ID_PATTERN = re.compile(r"\b(?:INV|PO|RC)-\d+\b")
NUMBER_PATTERN = re.compile(r"\$?\d[\d,]*(?:\.\d+)?")  # 10000, 10,000, $120.00


def draft_note(file_id, fields, result, provider):
    if result["status"] == "reconciled":
        return {"source": "none", "text": ""}
    facts = _facts(file_id, fields, result)
    try:
        text = provider.draft_note(NOTE_PROMPT.format(facts=json.dumps(facts, indent=2)))
    except Exception as error:  # a note failure must not stop the batch
        text = None
        facts["note_error"] = str(error)

    note = {"source": "template", "text": _template_note(facts)}
    if text:
        problem = check_model_note(text, facts)
        if problem is None:
            return {"source": "model", "text": text}
        note["rejected_model_note"] = {"text": text, "reason": problem}
    return note


def check_model_note(text, facts):
    """Return why a model-written note cannot be used, or None if it is fine.

    IDs and amounts are compared as whole tokens, so PO-12 does not count as
    citing PO-1, and 100 is not accepted just because 10000 is in the facts.
    """
    for key in REQUIRED_ID_KEYS:
        if facts.get(key) and not _mentions(text, facts[key]):
            return f"does not cite {facts[key]} ({key})"

    facts_text = json.dumps(facts)
    fact_ids = set(ID_PATTERN.findall(facts_text))
    for note_id in ID_PATTERN.findall(text):
        if note_id not in fact_ids:
            return f"mentions {note_id}, which is not in the verified facts"

    fact_numbers = set(re.findall(r"\d+", facts_text))
    for number in NUMBER_PATTERN.findall(text):
        if number.startswith("$") or "." in number:
            return f"writes {number} as dollars, but the facts are in cents"
        digits = number.replace(",", "")
        # Short numbers (quantities, "4 sentences") are not checked.
        if len(digits) >= 3 and digits not in fact_numbers:
            return f"mentions {number}, which is not in the verified facts"
    return None


def _mentions(text, token):
    """True if `token` appears in `text` as a whole token (not inside PO-12 or XINV-1)."""
    return re.search(rf"(?<![\w-]){re.escape(token)}(?![\w-])", text) is not None


def _facts(file_id, fields, result):
    facts = {"file_id": file_id, "status": result["status"], "findings": result["findings"]}
    if fields:
        facts["invoice_number"] = fields["invoice_number"]
        facts["supplier_id"] = fields["supplier_id"]
        if fields["po_id"]:
            facts["invoice_po_reference"] = fields["po_id"]
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
