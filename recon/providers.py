"""Where extraction responses come from.

Every provider has the same small interface:

    provider.extract(file_id, image_path) -> {"source", "model", "raw_text", ...}
    provider.draft_note(prompt) -> str or None

- SavedResponseProvider replays response files from disk. This is the default
  and needs no API key. data/model_responses/simulated/ holds SIMULATED
  responses; data/model_responses/live-<provider>/ holds REAL responses saved
  by the live providers below, and they replay the same way.
- GeminiProvider calls the Google Gemini REST API (standard library only).
- ClaudeProvider calls the Anthropic Messages API (optional `anthropic` SDK).

Live providers read the key from MODEL_API_KEY and the model from MODEL_NAME.
"""
import base64
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

EXTRACTION_PROMPT = """You are reading one supplier invoice image.
Return only a JSON object with exactly these keys:
  invoice_number, supplier_id, po_id, sku, quantity, unit_price, total
Rules:
- Copy text values exactly as printed.
- po_id is the purchase order reference. Use null if it is absent or shown as "(missing)".
- quantity is a whole number.
- unit_price and total are strings copied exactly as printed in USD, e.g. "24.00".
- Do not calculate, correct or guess any value. If a field cannot be read, use null.
If the image cannot be read at all, reply with one sentence saying so instead of JSON."""


class SavedResponseProvider:
    def __init__(self, responses_dir):
        self.responses_dir = Path(responses_dir)

    def extract(self, file_id, image_path):
        path = self.responses_dir / f"{file_id}.json"
        if not path.exists():
            raise RuntimeError(f"no saved response for {file_id} in {self.responses_dir}")
        return json.loads(path.read_text(encoding="utf-8"))

    def draft_note(self, prompt):
        return None  # notes fall back to the code-built template


class GeminiProvider:
    """Google Gemini generateContent over plain HTTPS.

    The key is sent in a header (never in the URL) and is never saved.
    Requests are spaced out and HTTP 429 is retried a few times, because the
    free tier allows only a handful of requests per minute. HTTP 503 ("high
    demand") is transient too, so it is retried the same way.
    """

    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    MAX_RETRIES = 3
    RETRY_STATUSES = (429, 503)

    def __init__(self, api_key, model, save_dir, min_interval=30,
                 urlopen=urllib.request.urlopen, sleep=time.sleep):
        self.api_key = api_key
        self.model = model
        self.save_dir = Path(save_dir)
        self.min_interval = min_interval  # seconds between requests
        self.urlopen = urlopen
        self.sleep = sleep
        self.last_request = None

    def extract(self, file_id, image_path):
        image_data = base64.standard_b64encode(Path(image_path).read_bytes()).decode("ascii")
        body = {
            "contents": [{"parts": [
                {"inline_data": {"mime_type": "image/png", "data": image_data}},
                {"text": EXTRACTION_PROMPT},
            ]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        reply = self._post(body)
        response = {
            "source": "live",
            "provider": "gemini",
            "model": self.model,
            "received_at": _now(),
            "file_id": file_id,
            "finish_reason": _finish_reason(reply),
            "raw_text": _gemini_text(reply),
        }
        save_response(self.save_dir, file_id, response)
        return response

    def draft_note(self, prompt):
        reply = self._post({"contents": [{"parts": [{"text": prompt}]}]})
        if _finish_reason(reply) != "STOP":
            return None
        return _gemini_text(reply).strip() or None

    def _post(self, body):
        request = urllib.request.Request(
            self.URL.format(model=self.model),
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            method="POST",
        )
        for attempt in range(self.MAX_RETRIES + 1):
            self._wait_for_turn()
            try:
                with self.urlopen(request, timeout=120) as reply:
                    return json.loads(reply.read())
            except urllib.error.HTTPError as error:
                details = error.read().decode("utf-8", "replace")
                if error.code not in self.RETRY_STATUSES or attempt == self.MAX_RETRIES:
                    raise RuntimeError(f"Gemini HTTP {error.code}: {details[:300]}")
                self.sleep(_retry_delay(details))

    def _wait_for_turn(self):
        if self.last_request is not None:
            waited = time.monotonic() - self.last_request
            if waited < self.min_interval:
                self.sleep(self.min_interval - waited)
        self.last_request = time.monotonic()


def _gemini_text(reply):
    """Join the text parts of the first candidate; label empty or cut-off replies."""
    candidates = reply.get("candidates") or []
    if not candidates:
        reason = reply.get("promptFeedback", {}).get("blockReason", "unknown")
        return f"(no response from model: {reason})"
    if candidates[0].get("finishReason") == "MAX_TOKENS":
        return "(response truncated at max tokens)"
    parts = candidates[0].get("content", {}).get("parts", [])
    return "".join(part["text"] for part in parts if "text" in part)


def _finish_reason(reply):
    candidates = reply.get("candidates") or []
    return candidates[0].get("finishReason") if candidates else None


def _retry_delay(error_body, default=60):
    """Read Google's suggested retryDelay (e.g. "17s") from an error body."""
    try:
        for detail in json.loads(error_body)["error"].get("details", []):
            if "retryDelay" in detail:
                return float(detail["retryDelay"].rstrip("s")) + 1
    except (ValueError, KeyError, TypeError):
        pass
    return default


class ClaudeProvider:
    def __init__(self, api_key, model, save_dir):
        import anthropic  # optional dependency; only needed for live Claude calls

        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.save_dir = Path(save_dir)

    def extract(self, file_id, image_path):
        image_data = base64.standard_b64encode(Path(image_path).read_bytes()).decode("ascii")
        message = self.client.messages.create(
            model=self.model,
            max_tokens=16000,  # thinking is always on for this model and uses part of this budget
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_data}},
                    {"type": "text", "text": EXTRACTION_PROMPT},
                ],
            }],
        )
        response = {
            "source": "live",
            "provider": "claude",
            "model": self.model,
            "received_at": _now(),
            "file_id": file_id,
            "stop_reason": message.stop_reason,
            "raw_text": _claude_text(message),
        }
        save_response(self.save_dir, file_id, response)
        return response

    def draft_note(self, prompt):
        message = self.client.messages.create(
            model=self.model,
            max_tokens=16000,  # thinking is always on for this model and uses part of this budget
            messages=[{"role": "user", "content": prompt}],
        )
        if message.stop_reason in ("refusal", "max_tokens"):
            return None
        return _claude_text(message).strip() or None


def _claude_text(message):
    # These become a labelled "failed" extraction instead of half-read JSON.
    if message.stop_reason == "refusal":
        return "(model refused the request)"
    if message.stop_reason == "max_tokens":
        return "(response truncated at max_tokens)"
    return "".join(block.text for block in message.content if block.type == "text")


def save_response(save_dir, file_id, response):
    save_dir.mkdir(parents=True, exist_ok=True)
    path = save_dir / f"{file_id}.json"
    path.write_text(json.dumps(response, indent=2) + "\n", encoding="utf-8")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


DEFAULT_MODELS = {"gemini": "gemini-3.5-flash-lite", "claude": "claude-opus-5-5"}


def make_provider(name, responses_dir, live_dir):
    if name == "saved":
        return SavedResponseProvider(responses_dir)
    if name not in DEFAULT_MODELS:
        raise SystemExit(f"unknown provider: {name}")
    api_key = os.environ.get("MODEL_API_KEY")
    if not api_key:
        raise SystemExit("MODEL_API_KEY is not set; use --provider saved to replay responses.")
    model = os.environ.get("MODEL_NAME") or DEFAULT_MODELS[name]
    if name == "gemini":
        return GeminiProvider(api_key, model, live_dir)
    return ClaudeProvider(api_key, model, live_dir)
