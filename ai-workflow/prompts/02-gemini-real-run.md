# Prompt 2: add Gemini and save a real run

This is the follow-up instruction that the coordinating session sent to the same subagent on 2026-11-12, after the candidate supplied a Google Gemini API key from a free-tier account. In the original message the key appeared in plain text. It has been replaced here with `<REDACTED>`.

The coordinating session divided the free-tier limits (15 requests per minute, 500 per day) among seven parallel subagents. That is why this prompt sets a budget of 40 requests and a minimum of 30 seconds between requests.

---

New follow-up for your invoices submission: add a Gemini provider and save one real model run.

The user supplied a Google Gemini API key. Use model `gemini-3.5-flash-lite` (verified working via REST: POST https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent with header `x-goog-api-key`, body {"contents":[{"parts":[...]}]}; text is at candidates[0].content.parts[*].text — skip parts that have no "text"; `responseMimeType: "application/json"` in generationConfig is supported). For the invoice images, send each image as a part `{"inline_data":{"mime_type":"image/png","data":"<base64>"}}` alongside the text prompt. Key: `<REDACTED>`

Do:
1. Add a small, readable Gemini provider next to your existing provider (standard library `urllib` only, no new dependency). Select it with env `MODEL_PROVIDER=gemini` (or a CLI flag, whichever fits your existing design); default model `gemini-3.5-flash-lite`, overridable by env. Keep the Anthropic path and the offline path working.
2. Unit-test it with a fake HTTP response (no live calls in the test suite).
3. Do ONE real end-to-end run with the live model over your invoice images and save the real responses/outputs labelled clearly as real (model name, timestamp), next to the existing simulated ones. Show the replay works on the saved real responses. Note in the README any fields the real model misread vs the expected results, and how your validation/review queue handled it — don't hide failures.
4. Update README, `.env.example` (variable names only), and `ai-workflow/` manifest/README to record Gemini usage honestly.

Hard limits — the key is shared by 7 agents running in parallel on a free tier (15 requests/min, 500/day total):
- At most 40 live requests total for your task. Do your debugging against fakes, not the live API.
- Wait at least 30 seconds between live requests. On HTTP 429, back off (respect any retryDelay) and retry at most 3 times.
- Pass the key ONLY via environment variable in the command (e.g. `MODEL_API_KEY=... python -m ...`). NEVER write it to any file: code, .env, logs, saved requests/responses, reports, README. Before finishing, grep your whole submission folder for the key prefix and confirm zero hits.
- Keep the code easy to read. Run the full test suite at the end and confirm it passes.

Final report under 150 words: what changed, live requests used, real-run outcome vs expected, test results, and confirmation the key grep is clean.
