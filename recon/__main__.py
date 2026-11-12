"""Command line entry point.

  python -m recon process [--provider saved|gemini|claude] [--responses DIR] [--state FILE]
  python -m recon report
  python -m recon serve [--port 8000]

The provider defaults to env MODEL_PROVIDER, else "saved" (offline replay).
"""
import argparse
import os
from pathlib import Path

from .providers import make_provider
from .records import load_reference_data
from .server import ReviewApp, make_server
from .storage import load_state, save_state
from .workflow import process_batch

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
REFERENCE_FILES = [DATA / "seed" / "seed.json", DATA / "additions.json"]
IMAGES_DIR = DATA / "images"
SIMULATED_RESPONSES = DATA / "model_responses" / "simulated"
RESPONSES_DIR = DATA / "model_responses"  # live runs save to live-<provider>/
STATE_FILE = ROOT / "var" / "state.json"


def main():
    parser = argparse.ArgumentParser(prog="recon")
    parser.add_argument("command", choices=["process", "report", "serve"])
    parser.add_argument("--provider", default=os.environ.get("MODEL_PROVIDER", "saved"),
                        choices=["saved", "gemini", "claude"])
    parser.add_argument("--responses", default=str(SIMULATED_RESPONSES),
                        help="folder of saved responses to replay (provider 'saved')")
    parser.add_argument("--state", default=str(STATE_FILE))
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    reference = load_reference_data(REFERENCE_FILES)
    provider = make_provider(args.provider, args.responses, RESPONSES_DIR / f"live-{args.provider}")
    state_path = Path(args.state)

    if args.command == "process":
        state = process_batch(reference, provider, IMAGES_DIR)
        save_state(state_path, state)
        print_report(state)
        print(f"\nSaved {state_path}")
        return

    state = load_state(state_path)
    if state is None:
        state = process_batch(reference, provider, IMAGES_DIR)
        save_state(state_path, state)

    if args.command == "report":
        print_report(state)
    else:
        app = ReviewApp(state, state_path, reference, provider, IMAGES_DIR)
        server = make_server(app, args.port)
        print(f"Review queue: http://127.0.0.1:{args.port}/  (Ctrl+C to stop)")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


def print_report(state):
    row = "{:<22} {:<11} {:<6} {:<5} {:>9} {:>8} {:>6}  {}"
    print(row.format("file_id", "status", "po", "rcpt", "expected", "billed", "diff", "extraction"))
    for file_id in state["order"]:
        invoice = state["invoices"][file_id]
        r = invoice["result"]
        print(row.format(file_id, r["status"], r["po_id"] or "-", r["receipt_id"] or "-",
                         _cents(r["expected_cents"]), _cents(r["billed_cents"]),
                         _cents(r["difference_cents"]), invoice["extraction"]["source"] or "-"))
    summary = state["summary"]
    counts = ", ".join(f"{k} {v}" for k, v in summary["counts"].items())
    print(f"\nCounts: {counts}")
    print(f"Recoverable (positive differences on matched invoices): {summary['recoverable_cents']} cents")
    print(f"Insight: {state['insight']}")


def _cents(value):
    return "-" if value is None else str(value)


if __name__ == "__main__":
    main()
