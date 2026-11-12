# Walkthrough: approach and findings

A short written presentation of this submission, as the brief allows ("a written walkthrough is sufficient"). Setup and details are in the [README](README.md).

## 1. Approach: the model reads, code decides

| Step | Done by | What happens |
|---|---|---|
| Read | Gemini | Each invoice image becomes a JSON object. |
| Validate | code | The schema and code checks reject missing or malformed fields. |
| Match | code | Matching uses the supplier ID and PO ID only, never the amount. |
| Reconcile | code | Expected and billed amounts are compared in integer cents, and duplicates are flagged. |
| Review | person | A reviewer corrects a field and the whole batch reruns. |

Only the first step uses a model. Matching, arithmetic and statuses are plain Python, covered by 47 tests. A failed invoice never stops the rest of the batch. A correction reruns the whole batch, because a fixed invoice number can change which invoice counts as the duplicate.

## 2. The supplied rules, applied literally

- **Match by reference.** Matching uses the supplier ID plus the PO ID only. One added invoice cites another supplier's PO with an identical amount, and it stays unresolved.
- **Integer cents, no rounding.** "24.00" becomes 2400 through `Decimal`. A fraction of a cent is rejected as invalid, never rounded.
- **Duplicates.** When two invoices have the same supplier and invoice number, the first is kept. Later ones are flagged and never counted as recoverable.
- **Don't guess.** Missing or conflicting references stay unresolved. Where the rules are silent, the choice is listed in the README. For example, an invoice billing 4 units when 3 were received is marked discrepant with a quantity finding, and no amount is claimed.

## 3. Every required check passes

| Check | Expected (written by hand first) | Observed |
|---|---|---|
| Clean invoice matches PO-1 and RC-1 | reconciled, difference 0 | pass |
| Wrong unit price | discrepant, +2000 cents | pass |
| Duplicate invoice | flagged, not payable | pass |
| Missing PO reference | unresolved, no amount | pass |
| Correction reruns the batch | +800 → 0; recoverable 2800 → 2000 | pass |
| Seeds vs `expected-seed-results.json` | all fields equal | pass |

The expected values were calculated before the app ran, and they are stored separately from the app's output.

## 4. What the real model did (gemini-3.5-flash-lite)

- **7 / 7** readable invoices were read correctly, with every field matching the ground truth.
- **1** blurred invoice was reported as unreadable. It was marked failed and the batch continued.
- **2000 cents** is recoverable, which equals the hand-checked total.

The run used 16 live requests. Two came back with HTTP 503 ("high demand"). They were recorded as failed and the batch carried on. I made 503 retryable and requested only those two images again. Every real response is saved, and replaying them is the app's default.

## 5. A model error, caught and fixed

Gemini's note for the duplicate invoice said:

> "…identified as a duplicate of the clean record. No purchase order or receipt IDs are present…"

The invoice prints PO-1, so the note was wrong.

- **Cause:** when an invoice isn't matched, the PO printed on it was never passed to the model.
- **Fix:**
  - The facts now include the printed PO.
  - `check_model_note` rejects any note that omits a given ID, or mentions an ID or amount that isn't in the facts.
  - IDs and amounts are compared as whole tokens, so `PO-12` doesn't count as citing `PO-1`.
  - A rejected note falls back to a template, and the reason is saved.
- **Proof:** `tests/test_notes.py` runs the model's real notes from the live run. This note is rejected, and the grounded ones are kept.

One live call confirmed that Gemini accepts the stricter response schema: for the blurred image it returned `"readable": false`. The note check itself has not been rerun live.

## 6. How I used AI

- **Built by:** Claude Code agents (claude-opus-5-5). The full instructions they received are in `ai-workflow/prompts/`.
- **My part:** I chose the task, reviewed the output and the real run, and directed the corrections. This took about 1 hour of my own time.
- **In the app:** Gemini 3.5 Flash Lite over REST, using only the standard library. The key is read from the environment and never stored.
- **Verification:** the 47 tests run on every push through GitHub Actions. Real responses replay offline.

## 7. What this doesn't prove yet

- Eight fictional invoices say little about accuracy on real documents.
- The note check is tested on real notes, but has not been rerun against the live API.
- The correction demo uses a labelled, simulated misread, because the real model made none.
- State is one JSON file. PDF input and multi-line invoices are out of scope.

Next, I'd test a larger set of harder scans, run the note check live and add PDF input.
