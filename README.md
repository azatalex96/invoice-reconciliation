# Invoice reconciliation and review (take-home B)

[![tests](https://github.com/azatalex96/invoice-reconciliation/actions/workflows/tests.yml/badge.svg)](https://github.com/azatalex96/invoice-reconciliation/actions/workflows/tests.yml)

A small local accounts-payable review tool:

- A document-capable model (Gemini) reads each invoice image.
- Code validates what the model returned.
- Each invoice is matched to its purchase order and receipt by reference only.
- Expected and billed amounts are compared in integer cents, and duplicates are flagged.
- A review queue lets a reviewer correct a field and rerun the batch.

It uses the Python 3.12 standard library only. The app and tests need no API key, because by default the app replays a saved real Gemini run.

## Results

These are from the saved real `gemini-3.5-flash-lite` run, replayed offline. They are checked by `python -m unittest`.

| # | Minimum demonstration check | Expected (hand-checked) | Observed |
|---|---|---|---|
| 1 | `clean` matches PO-1 / RC-1 and the amounts agree | reconciled, expected 10000 / billed 10000 / difference 0 | pass |
| 2 | `wrong-price` discrepancy, linked to the invoice and the agreed price | discrepant, +2000 cents, cites INV-2 and PO-2 at an agreed 2000 | pass |
| 3 | `duplicate` is flagged and kept out of the totals | duplicate of `clean`, not payable | pass |
| 4 | `missing-reference` stays unresolved, with no invented match or amount | unresolved, expected amount null | pass |
| 5 | A correction reruns the batch and survives a restart | `corrected-total` +800 → 0. Recoverable 2800 → 2000. | pass (simulated misread, see below) |
| - | The seeds reproduce `expected-seed-results.json` | all fields equal | pass |

Batch summary for the real run: 2 reconciled, 2 discrepant, 1 duplicate, 2 unresolved and 1 failed (the deliberately blurred image). The recoverable amount is **2000 cents**.

## Run it

```
python -m unittest -v                 # 42 tests, no network
python -m recon process               # replay the real Gemini run, save var/state.json, print the table
python -m recon serve                 # review queue on http://127.0.0.1:8000/
python -m recon report                # print saved results, including corrections made in the UI
```

To try the **correction demo**, use the simulated set. It includes a deliberate misread total (98.00 instead of 90.00):

```
python -m recon process --responses data/model_responses/simulated
python -m recon serve
```

Then open `corrected-total`, set `total_cents` to `9000`, and rerun. The invoice becomes reconciled and the recoverable amount drops from 2800 to 2000 cents.

For a **live model run**, set the key in the environment only:

```
# PowerShell: $env:MODEL_API_KEY="..."; $env:MODEL_PROVIDER="gemini"; python -m recon process
MODEL_API_KEY=... MODEL_PROVIDER=gemini python -m recon process
```

- `MODEL_PROVIDER` (or `--provider`) selects `saved` (the default), `gemini` or `claude`. Claude needs `pip install anthropic` and has never been called for real.
- `MODEL_NAME` overrides the model.
- Live responses are saved to `data/model_responses/live-<provider>/` so they can be replayed without a key.

## How it works

```
image → provider (Gemini / Claude / saved replay) → extraction.parse_response   invalid → failed
      → reconcile_batch: duplicate? → match_invoice (supplier + PO only) → expected vs billed
      → notes.draft_note (model rewrites verified facts; check_model_note guards it) → state.json
      → review queue: correction → rerun the whole batch (a fix can change which invoice is the duplicate)
```

| Module | Responsibility |
|---|---|
| `recon/providers.py` | Saved-response replay, Gemini (`urllib`, enforced JSON schema), Claude (SDK). Prompt: `EXTRACTION_PROMPT`. |
| `recon/extraction.py` | Validates the model's JSON and converts "24.00" to 2400 cents with `Decimal` |
| `recon/matching.py` | Matching rule 2: supplier ID + PO ID, then receipt lookup. Amounts are never used. |
| `recon/reconcile.py` | Statuses, findings, duplicates, recoverable total (rules 3–4) |
| `recon/notes.py` | Draft notes from verified facts and a check on model-written notes. Batch insight. |
| `recon/workflow.py` | Extract → validate → reconcile → notes. Corrections and review status. |
| `recon/server.py`, `recon/static/index.html` | Local JSON API and the review page |
| `recon/storage.py`, `recon/records.py` | Atomic JSON state file. Reference tables. |

**Domain rules → code.**
- **Rule 2:** a missing PO, an unknown PO, or a PO belonging to another supplier or SKU makes the invoice unresolved (`matching.match_invoice`).
- **Rule 3:** expected = ordered quantity × agreed unit price. The billed quantity is compared with both the ordered and the received quantity (`reconcile._findings`).
- **Rule 4:** a duplicate has the same supplier ID and invoice number, and the first one in arrival order is kept. Only positive differences on `discrepant` invoices count as recoverable (`reconcile.summarize`).

**Rounding.** There is no rounding, because every amount is in integer cents and nothing is divided. An amount with fractions of a cent is rejected as an invalid extraction.

**Statuses.** The statuses are `failed`, `duplicate`, `unresolved`, `discrepant` and `reconciled`. If an invoice's own total ≠ quantity × unit price, that is reported as an "Invoice arithmetic" finding.

## Checking the model

The app never trusts the model's output as is:

- **Extraction.** Gemini must return JSON matching `EXTRACTION_SCHEMA`, including a `readable` flag. Code then rejects any missing field, any non-integer quantity or any malformed amount, and marks that invoice `failed` while the rest of the batch continues.
- **Notes.** The model rewrites only facts that code has already checked. `check_model_note` rejects a note in two cases, and the note falls back to a template with the reason recorded:
  - it fails to cite the invoice, PO or receipt IDs it was given
  - it mentions an ID or amount that is not in those facts
- **Failures.** API errors are recorded per invoice. HTTP 429 and 503 are retried at most 3 times, at least 30 s apart.

## Real Gemini run (12 Nov 2026)

There were 16 live requests in total. The real responses are saved in `data/model_responses/live-gemini/`, each labelled with the model name and a timestamp. The app output is in `data/real-run/`.

| Invoice | What Gemini returned | Result |
|---|---|---|
| 7 readable invoices | every field correct against the ground truth | matches the expected results |
| `unreadable` (deliberately blurred) | JSON with every field null | validation rejects it, so it is `failed` and visible in the queue |

What went wrong, and what changed as a result:

1. **HTTP 503 errors.** Two extractions got HTTP 503 ("high demand"). They were recorded as `failed` and the batch continued. 503 is now retried, and only those two images were requested again.
2. **A misleading note.** Gemini's note for `duplicate` said "no purchase order or receipt IDs are present", but the invoice prints PO-1. The cause was that the PO printed on an invoice wasn't passed to the model when no match was made. The facts now include it (`invoice_po_reference`), and `check_model_note` rejects a note that doesn't cite it. `tests/test_notes.py` runs the real notes from that run through the check: the duplicate note is rejected, and the correct ones are kept.
3. **Prompt and JSON mode disagreed.** The prompt asked for a plain sentence when the image was unreadable, but JSON mode forced an object. The prompt now uses an explicit `readable` field, enforced by the schema.

Changes 2 and 3 are covered by tests. They have not been rerun against the live API.

## Data

- **Seeds.** `data/seed/` holds the 4 starter invoices with their POs and receipts, copied unchanged with `expected-seed-results.json`.
- **Additions.** `data/additions.json` holds 4 hand-written cases, rendered with `data/render_additions.py`:
  - `conflicting-reference`: its amount equals PO-1 exactly, which proves amounts are not used for matching.
  - `short-receipt`: 4 billed, 3 received.
  - `corrected-total`: used for the correction demo.
  - `unreadable`: a deliberately blurred image.
- **Expected results.** `data/expected-reference-results.json` was written by hand before running the app. It is kept separate from the app's output.
- **Simulated responses.** `data/model_responses/simulated/` holds simulated responses, labelled `"source": "simulated"`. They are used by most tests and by the correction demo, because the real model misread nothing.

## Ambiguities and choices

1. **Duplicates.** When two invoices share a supplier and invoice number, the first one in arrival order is kept and the later one is flagged. This reproduces the seed expectation.
2. **Short receipt.** Billing 4 units when 3 were received, at the agreed price, gives a difference of 0 under rule 3. The invoice is still `discrepant`, with a quantity finding, but no amount is claimed, because `domain.md` defines no shortfall amount.
3. **Conflicts.** A PO for a different SKU, a missing receipt, or several receipts for the same PO each leave the invoice unresolved.
4. **Undercharges.** An undercharge is `discrepant` but is never added to the recoverable total.
5. **Failed extractions.** A `failed` extraction can't be corrected field by field. That would need manual entry or a new extraction, which is out of scope.

## Limitations

- **Small real run.** There was one real run with Gemini only, over eight fictional invoices, which says little about real-world accuracy. The Claude path has never been called for real.
- **Notes on replay.** Replaying the real run uses template notes, because saved responses cover extraction only. The live run's model notes are in `data/real-run/live-run-state.json`.
- **Simple storage.** State is a single JSON file, and running `process` again discards corrections.
- **Out of scope.** PDF input, export and invoices with several lines are not implemented.

## AI workflow

The app was built with Claude Code subagents. The full instructions they were given, the configuration, and a worked example of a correction are in `ai-workflow/`.
