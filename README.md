# Invoice reconciliation and review (take-home B)

A small local accounts-payable review tool. It reads invoice images through an
extraction provider, validates the result, matches each invoice to a purchase
order and receipt, works out expected against billed amounts in integer cents,
flags duplicates, and serves a review queue where a reviewer can correct an
extracted field and rerun the batch.

Python 3.12 standard library only. No API key is needed to run the app or the tests.

## How to run

```
cd submissions/invoices
python -m unittest -v              # 36 tests (no network), including the seed-results check
python -m recon process            # extract + reconcile all 8 invoices, save var/state.json, print a table
python -m recon serve              # review queue at http://127.0.0.1:8000/  (processes first if no state)
python -m recon report             # print the saved results (shows corrections made in the UI)
```

To start over, run `python -m recon process` again. It rebuilds `var/state.json` and drops corrections.

Replay the saved **real** Gemini run (no key, no network):
```
python -m recon process --responses data/model_responses/live-gemini --state data/real-run/replay-state.json
```

Live model extraction (needs a key; responses are saved to `data/model_responses/live-<provider>/`):
```
# PowerShell: $env:MODEL_API_KEY="..."; $env:MODEL_PROVIDER="gemini"; python -m recon process
MODEL_API_KEY=... MODEL_PROVIDER=gemini python -m recon process --state data/real-run/live-run-state.json
MODEL_API_KEY=... python -m recon process --provider claude      # needs: pip install anthropic (never run)
```
`MODEL_PROVIDER` (or `--provider`) picks `saved` (default), `gemini` or `claude`. `MODEL_NAME` overrides the model.

## Design

```
data/seed/                 starter-pack files, copied unchanged (seed.json, expected-seed-results.json, domain.md, ...)
data/additions.json        4 added invoices + PO-3/PO-4 + RC-3/RC-4 (same shape as seed.json)
data/images/               8 invoice PNGs (4 original, 4 rendered by render_additions.py)
data/model_responses/simulated/   SIMULATED extraction responses, one per image (see "Model use" below)
data/model_responses/live-gemini/ REAL gemini-3.5-flash-lite responses, one per image, with timestamps
data/real-run/             saved app output of the live run and of its offline replay
data/expected-reference-results.json   hand-checked expectations, kept apart from app output
recon/records.py           load POs, receipts and the document list
recon/providers.py         extraction providers: saved-response replay (default), Gemini (urllib), Claude (SDK)
recon/extraction.py        validate the raw model text; convert "24.00" to 2400 cents
recon/matching.py          supplier + PO matching, receipt lookup (rule 2)
recon/reconcile.py         statuses, expected vs billed, duplicates, summary (rules 3-4)
recon/notes.py             draft notes from verified findings; batch insight
recon/workflow.py          extract -> validate -> reconcile -> notes; corrections; review state
recon/storage.py           one JSON state file, written atomically
recon/server.py            http.server JSON API + static page
recon/static/index.html    review queue (vanilla JS)
tests/                     unittest suites
```

The flow is: provider returns raw text → `parse_response` validates it (invalid → `failed`) → `reconcile_batch` decides a status for every invoice in arrival order → notes are drafted → the state is saved. A correction adds an entry to the invoice's `corrections` list. The original extraction is never overwritten. The current fields are rebuilt as original plus corrections, and the whole batch is reconciled again, because a corrected invoice number can change which invoice counts as the duplicate.

## How the domain rules map to code

| Rule (data/seed/domain.md) | Code |
|---|---|
| 1. PO = SKU, qty, unit price; receipt = qty delivered; invoice = billed | `records.py`, fields in `extraction.EDITABLE_FIELDS` |
| 2. Match by supplier ID + PO ID; missing or conflicting reference stays unresolved; never by amount | `matching.match_invoice`: missing PO, unknown PO, PO of another supplier, or PO for another SKU → unresolved. Amounts are never looked at. |
| 3. Expected = ordered qty × agreed unit price; compare billed qty with ordered **and** received; integer cents | `reconcile.reconcile_invoice` and `_findings` |
| 4. Duplicate = same supplier ID + invoice number; difference = billed − expected (positive = overcharge); no duplicates/unresolved in recoverable totals | `reconcile_batch` (first occurrence kept), `summarize` (only `discrepant` positive differences) |

**Rounding.** Amounts are integer cents everywhere and nothing is divided, so there is no rounding. The model copies amounts as printed ("24.00"), and `usd_to_cents` converts them with `Decimal`. An amount with fractions of a cent is rejected as an invalid extraction instead of being rounded.

**Statuses.** `failed` (no valid extraction), `duplicate`, `unresolved`, `discrepant` (any price, quantity, arithmetic or amount finding), `reconciled`. The billed amount is the invoice total. If total ≠ qty × unit price on the invoice itself, that is reported as an "Invoice arithmetic" finding.

## Data

- Seeds: the 4 starter invoices, POs and receipts, copied unchanged.
- Additions: I wrote these by hand. No random generation, so there is no seed. They use the two supplied layouts, and the images are rendered with `data/render_additions.py`, adapted from the pack's script:
  - `conflicting-reference` (INV-6, S2 cites PO-1, which belongs to S1). Its amount equals PO-1 exactly, so the test proves amount matching is not used.
  - `short-receipt` (INV-4, PO-3 ordered 4, received 3, billed 4 at the agreed price).
  - `corrected-total` (INV-5, PO-4). The simulated extraction misreads the total as 98.00 instead of 90.00, and the reviewer corrects `total_cents` to 9000.
  - `unreadable` (INV-7). The image is deliberately blurred and the simulated response is not JSON. This is a deliberate invalid case, not a data error.
- `data/make_simulated_responses.py` writes the simulated responses from the ground-truth records, plus the two deliberate faults.
- Expected results: `data/expected-reference-results.json`. I wrote them by hand before running the app, with the arithmetic shown for each case. The starter `expected-seed-results.json` stays untouched in `data/seed/`.

## Minimum demonstration (observed with `python -m unittest` and `python -m recon process`)

| # | Check | Expected | Observed |
|---|---|---|---|
| 1 | `clean` matches PO-1 / RC-1, amounts agree | reconciled, 10000 / 10000 / 0 | same (pass) |
| 2 | `wrong-price` discrepancy, linked to invoice and agreed price | discrepant, 10000 / 12000 / +2000, cites INV-2, PO-2 agreed 2000 | same (pass) |
| 3 | `duplicate` flagged and excluded from totals | duplicate of `clean`, count_as_payable false | same (pass) |
| 4 | `missing-reference` unresolved, no invented match or amount | unresolved, expected null | same (pass) |
| 5 | Correct `corrected-total` total to 9000, rerun, restart | discrepant +800 → reconciled 0; persists after reload/restart | same (pass; tested through the HTTP server and a restart) |
| - | Batch totals before / after correction | recoverable 2800 → 2000 cents | same (pass) |
| - | Seeds reproduce `expected-seed-results.json` | all fields equal | pass (seed-only batch and full batch) |

No check fails.

## Model use and honesty about responses

- **Simulated responses** (`data/model_responses/simulated/`, `"source": "simulated"`) drive the default run and most tests. They include two deliberate faults: a misread total and an unreadable image.
- **Real responses**: `data/model_responses/live-gemini/` holds one real `gemini-3.5-flash-lite` response per image, each labelled `"source": "live"` with the model name and a `received_at` timestamp. No key or request is saved.
- `GeminiProvider` (`recon/providers.py`) uses only `urllib`. It POSTs the PNG as `inline_data` plus `EXTRACTION_PROMPT` to `generateContent`, with `responseMimeType: application/json` and otherwise default generation settings. The key goes in the `x-goog-api-key` header and comes from `MODEL_API_KEY`. Requests are spaced at least 30 s apart. HTTP 429/503 are retried at most 3 times using Google's `retryDelay` (default 60 s). Any other error is recorded as `failed` and the batch moves on. All of this is tested with a fake `urlopen` (`tests/test_providers.py`). Notes from the live run were drafted by the same model.
- `ClaudeProvider` (`recon/providers.py`) sends the PNG and a fixed prompt (`EXTRACTION_PROMPT`) to the Anthropic Messages API (`claude-opus-5-5`, overridable with `MODEL_NAME`). It uses default sampling and thinking settings and `max_tokens=16000`, and reads the key from `MODEL_API_KEY`. Each raw response is saved under `data/model_responses/live/` so it can be replayed without a key. This path has only been tested offline with a fake client (`tests/test_providers.py`), never against the real API.
- Draft notes: with a live model, `draft_note` asks the model to rewrite only the verified facts. With the replay provider, a code template is used, labelled `template`. A refusal or a response cut off at `max_tokens` becomes a labelled `failed` extraction. Any model or API exception is caught, so the invoice is marked `failed` (extraction) or falls back to the template (note), and the batch continues (`tests/test_extraction.py`).

## Real Gemini run (12 Nov 2026, 16 live requests in total)

**Run 1** (`data/real-run/live-run-state.json`, 14 requests: 8 extractions + 6 notes). Two extractions, `wrong-price` and `missing-reference`, got HTTP **503 "model is experiencing high demand"**. At that point only 429 was retried, so they were recorded as `failed` with the error text, and the other 6 invoices were still processed. That run's summary was therefore wrong for those two invoices: reconciled 2, discrepant 1, duplicate 1, unresolved 1, failed 3, recoverable 0. After this I made 503 retryable like 429 and re-requested only those two images (2 requests). Then I replayed all 8 saved real responses offline (`data/real-run/replay-state.json`, `tests/test_real_responses.py`).

| Invoice | Real model read | vs ground truth | App result (replay) |
|---|---|---|---|
| clean, wrong-price, duplicate, missing-reference | all fields correct (null PO on missing-reference) | match | same as `expected-seed-results.json` |
| conflicting-reference, short-receipt | all fields correct | match | unresolved / discrepant (qty 4 billed vs 3 received), as expected |
| corrected-total | total read correctly as **90.00** | match | reconciled 9000/9000. The 98.00 misread exists only in the simulated data, so the correction demo still uses simulated input. |
| unreadable (blurred) | JSON object with every field `null` (not the "cannot read" sentence the prompt asked for) | n/a | validation rejects it, giving `failed` ("invoice_number is missing"), visible in the queue |

Replay summary: reconciled 2, discrepant 2, duplicate 1, unresolved 2, failed 1, recoverable 2000 cents. This equals the hand-checked "after correction" expectation. The model misread no fields. One model-drafted note was imprecise: for `duplicate` it said "no purchase order or receipt IDs are present", when the app simply does not match duplicates. Notes stay drafts. Eight fictional invoices say little about real-world extraction accuracy.

## Ambiguities and choices (not new business rules)

1. **Which duplicate is "the" duplicate.** The first invoice in arrival order (file order in seed.json, then additions.json) is kept and later ones are flagged. This reproduces the seed expectation.
2. **Billed quantity ≠ received quantity at the agreed price** (`short-receipt`). The difference is 0 under rule 3, but rule 3 also says to compare quantities. I mark it `discrepant` with a quantity finding and claim **no** amount, because domain.md defines no shortfall amount.
3. **Conflicting SKU** between the invoice and the cited PO is treated as a conflicting reference, so the invoice is unresolved.
4. **Missing or multiple receipts** for a matched PO → unresolved, because quantity cannot be compared with what was received. The seeds do not contain this case.
5. **Undercharges** (negative difference) are `discrepant` but never added to the recoverable total.
6. A `failed` extraction cannot be corrected field by field in the UI. It would need manual entry or re-extraction, which I left out of scope.

## Limitations

- One small real run with Gemini only. The Claude path has never been called for real. Replay of the real run uses template notes, because saved responses cover extraction only. The model notes from the live run are kept in `data/real-run/live-run-state.json`.
- The review page was checked by running its JavaScript under Node with a stubbed DOM (every invoice, plus one with a correction) and by fetching it over HTTP. I did not click through it in a real browser.
- PDF input, export, and multi-line invoices are not implemented. There is a single review status (open/reviewed) with a comment.
- The state is one JSON file with no concurrency beyond a process lock. Running `process` again discards corrections.
- No git history was created by me. The folder is ready to commit.
- Time: built in one AI agent session. Wall-clock time was not measured precisely. This README is the written walkthrough (no recording).

## AI workflow

See `ai-workflow/README.md` and `ai-workflow/manifest.json`.
