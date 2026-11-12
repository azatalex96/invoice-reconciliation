"""The end-to-end flow: extract -> validate -> reconcile -> draft notes -> save.

The state dict keeps, per invoice, the original extraction untouched, the
list of reviewer corrections, the current fields (original + corrections),
the reconciliation result, a draft note, and the review status.
"""
from datetime import datetime, timezone

from .extraction import ExtractionError, coerce_correction, parse_response
from .notes import batch_insight, draft_note
from .reconcile import reconcile_batch, summarize


def process_batch(reference, provider, images_dir):
    """Extract every document and reconcile the batch. One failure never stops the rest."""
    invoices = {}
    for file_id in reference.file_ids:
        image_path = images_dir / f"{file_id}.png"
        invoices[file_id] = {
            "file_id": file_id,
            "image": image_path.name,
            "extraction": _extract(provider, file_id, image_path),
            "corrections": [],
            "review": {"status": "open", "comment": ""},
        }
    state = {"order": list(reference.file_ids), "invoices": invoices, "processed_at": _now()}
    rerun_reconciliation(state, reference, provider)
    return state


def apply_correction(state, reference, provider, file_id, field, value):
    """Record a reviewer correction and rerun reconciliation for the whole batch.

    The whole batch is rerun because a corrected invoice number or supplier can
    change which invoice is a duplicate of which.
    """
    invoice = state["invoices"][file_id]
    if invoice["extraction"]["fields"] is None:
        raise ExtractionError("extraction failed for this invoice; there are no fields to correct")
    new_value = coerce_correction(field, value)
    invoice["corrections"].append({
        "field": field,
        "old": invoice["fields"][field],
        "new": new_value,
        "at": _now(),
    })
    rerun_reconciliation(state, reference, provider)


def set_review(state, file_id, status, comment):
    if status not in ("open", "reviewed"):
        raise ValueError("review status must be 'open' or 'reviewed'")
    state["invoices"][file_id]["review"] = {"status": status, "comment": comment, "at": _now()}


def rerun_reconciliation(state, reference, provider):
    items = []
    for file_id in state["order"]:
        invoice = state["invoices"][file_id]
        invoice["fields"] = current_fields(invoice)
        items.append({"file_id": file_id, "fields": invoice["fields"],
                      "error": invoice["extraction"]["error"]})

    results = reconcile_batch(items, reference)
    for file_id, result in results.items():
        invoice = state["invoices"][file_id]
        old_result = invoice.get("result")
        invoice["result"] = result
        # Only redraft when the result changed, to avoid needless model calls.
        if result != old_result or "note" not in invoice:
            invoice["note"] = draft_note(file_id, invoice["fields"], result, provider)
    state["summary"] = summarize(results)
    state["insight"] = batch_insight(results)


def current_fields(invoice):
    original = invoice["extraction"]["fields"]
    if original is None:
        return None
    fields = dict(original)
    for correction in invoice["corrections"]:
        fields[correction["field"]] = correction["new"]
    return fields


def _extract(provider, file_id, image_path):
    """Call the provider and validate its answer. Errors are recorded, not raised."""
    record = {"source": None, "model": None, "raw_text": None, "fields": None, "error": None}
    try:
        response = provider.extract(file_id, image_path)
        record.update(source=response["source"], model=response.get("model"),
                      raw_text=response["raw_text"])
        record["fields"] = parse_response(response["raw_text"])
    except ExtractionError as error:
        record["error"] = f"invalid extraction: {error}"
    except Exception as error:  # model/API/network failure
        record["error"] = f"provider error: {error}"
    return record


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
