"""Shared paths and a helper to run the batch on the bundled data."""
import json
from pathlib import Path

from recon.providers import SavedResponseProvider
from recon.records import load_reference_data
from recon.workflow import process_batch

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SEED_FILE = DATA / "seed" / "seed.json"
ADDITIONS_FILE = DATA / "additions.json"
IMAGES_DIR = DATA / "images"
SIMULATED = DATA / "model_responses" / "simulated"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run_batch(reference_files=(SEED_FILE, ADDITIONS_FILE)):
    reference = load_reference_data(reference_files)
    provider = SavedResponseProvider(SIMULATED)
    return reference, provider, process_batch(reference, provider, IMAGES_DIR)


def fields(**overrides):
    """A valid set of extracted fields for PO-1, changed by keyword."""
    base = {"invoice_number": "INV-9", "supplier_id": "S1", "po_id": "PO-1", "sku": "CAB-1",
            "quantity": 5, "unit_cents": 2000, "total_cents": 10000}
    base.update(overrides)
    return base
