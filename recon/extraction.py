"""Turn a model's raw text response into validated invoice fields.

The model is asked to copy amounts exactly as printed (e.g. "24.00"). Code,
not the model, converts them to integer cents. No rounding is ever applied:
an amount with more than two decimal places is rejected as invalid.
"""
import json
from decimal import Decimal, InvalidOperation


class ExtractionError(Exception):
    """The response could not be turned into valid invoice fields."""


TEXT_FIELDS = ["invoice_number", "supplier_id", "sku"]

# Field names after validation. Reviewers correct these in the app.
EDITABLE_FIELDS = {
    "invoice_number": str,
    "supplier_id": str,
    "po_id": str,
    "sku": str,
    "quantity": int,
    "unit_cents": int,
    "total_cents": int,
}


def parse_response(raw_text):
    """Validate a raw model response and return normalised fields."""
    data = _load_json_object(raw_text)

    fields = {}
    for name in TEXT_FIELDS:
        fields[name] = _required_text(data, name)
    fields["po_id"] = _optional_reference(data.get("po_id"))
    fields["quantity"] = _quantity(data.get("quantity"))
    fields["unit_cents"] = usd_to_cents(data.get("unit_price"), "unit_price")
    fields["total_cents"] = usd_to_cents(data.get("total"), "total")
    return fields


def usd_to_cents(value, name):
    """Convert a printed USD amount such as "120.00" to 12000 cents."""
    if isinstance(value, bool) or value is None:
        raise ExtractionError(f"{name} is missing")
    text = str(value).replace("$", "").replace(",", "").strip()
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise ExtractionError(f"{name} is not a number: {value!r}")
    cents = amount * 100
    if cents != cents.to_integral_value() or amount < 0:
        raise ExtractionError(f"{name} is not a valid USD amount: {value!r}")
    return int(cents)


def coerce_correction(field, value):
    """Validate a reviewer's corrected value for one field."""
    if field not in EDITABLE_FIELDS:
        raise ExtractionError(f"{field} cannot be corrected")
    if field == "po_id":
        return _optional_reference(value)
    if EDITABLE_FIELDS[field] is int:
        try:
            number = int(str(value).strip())
        except ValueError:
            raise ExtractionError(f"{field} must be a whole number")
        if number < 0:
            raise ExtractionError(f"{field} must not be negative")
        return number
    text = str(value).strip()
    if not text:
        raise ExtractionError(f"{field} must not be empty")
    return text


def _load_json_object(raw_text):
    text = raw_text.strip()
    # Models sometimes wrap JSON in a ``` fence; accept that, nothing looser.
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise ExtractionError("response is not JSON: " + raw_text[:80])
    if not isinstance(data, dict):
        raise ExtractionError("response is not a JSON object")
    return data


def _required_text(data, name):
    value = data.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ExtractionError(f"{name} is missing")
    return value.strip()


def _optional_reference(value):
    """A blank or "(missing)" PO reference becomes None (unresolved later)."""
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() in ("(missing)", "missing", "none", "null"):
        return None
    return text


def _quantity(value):
    if isinstance(value, bool):
        raise ExtractionError("quantity is not a whole number")
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if not isinstance(value, int) or value < 0:
        raise ExtractionError(f"quantity is not a whole number: {value!r}")
    return value
