"""The live providers, exercised offline with fakes (no API key, no network)."""
import io
import json
import urllib.error
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from recon.extraction import parse_response
from recon.providers import ClaudeProvider, GeminiProvider
from tests.helpers import IMAGES_DIR

FAKE_JSON = json.dumps({"invoice_number": "INV-1", "supplier_id": "S1", "po_id": "PO-1", "sku": "CAB-1",
                        "quantity": 5, "unit_price": "20.00", "total": "100.00"})


class FakeMessages:
    def __init__(self, stop_reason="end_turn"):
        self.stop_reason = stop_reason
        self.calls = []

    def create(self, **request):
        self.calls.append(request)
        return SimpleNamespace(stop_reason=self.stop_reason,
                               content=[SimpleNamespace(type="text", text=FAKE_JSON)])


def fake_provider(save_dir, stop_reason="end_turn"):
    provider = ClaudeProvider.__new__(ClaudeProvider)  # skip the real SDK client
    provider.client = SimpleNamespace(messages=FakeMessages(stop_reason))
    provider.model = "claude-opus-5-5"
    provider.save_dir = Path(save_dir)
    return provider


class ClaudeProviderTest(unittest.TestCase):
    def test_sends_image_and_saves_response_for_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = fake_provider(tmp)
            response = provider.extract("clean", IMAGES_DIR / "clean.png")

            request = provider.client.messages.calls[0]
            content = request["messages"][0]["content"]
            self.assertEqual(content[0]["type"], "image")
            self.assertEqual(content[0]["source"]["media_type"], "image/png")
            self.assertNotIn("temperature", request)

            self.assertEqual(response["source"], "live")
            self.assertEqual(parse_response(response["raw_text"])["total_cents"], 10000)
            saved = json.loads((Path(tmp) / "clean.json").read_text())
            self.assertEqual(saved["raw_text"], FAKE_JSON)

    def test_refusal_becomes_invalid_extraction_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            response = fake_provider(tmp, "refusal").extract("clean", IMAGES_DIR / "clean.png")
            self.assertEqual(response["raw_text"], "(model refused the request)")

    def test_truncated_response_is_labelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            response = fake_provider(tmp, "max_tokens").extract("clean", IMAGES_DIR / "clean.png")
            self.assertEqual(response["raw_text"], "(response truncated at max_tokens)")


class FakeUrlopen:
    """Returns queued replies; an int queues an HTTP error with that status."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, int):
            body = json.dumps({"error": {"details": [{"retryDelay": "7s"}]}}).encode()
            raise urllib.error.HTTPError(request.full_url, reply, "error", {}, io.BytesIO(body))
        return io.BytesIO(json.dumps(reply).encode())


def gemini_reply(text, finish_reason="STOP"):
    # Gemini may return parts without "text" (e.g. thought signatures); they are skipped.
    return {"candidates": [{"finishReason": finish_reason,
                            "content": {"parts": [{"thoughtSignature": "x"}, {"text": text}]}}]}


def gemini_provider(save_dir, urlopen, sleeps):
    return GeminiProvider("test-key", "gemini-3.5-flash-lite", save_dir, min_interval=0,
                          urlopen=urlopen, sleep=sleeps.append)


class GeminiProviderTest(unittest.TestCase):
    def test_sends_image_and_saves_labelled_response(self):
        urlopen = FakeUrlopen(gemini_reply(FAKE_JSON))
        with tempfile.TemporaryDirectory() as tmp:
            response = gemini_provider(tmp, urlopen, []).extract("clean", IMAGES_DIR / "clean.png")

            request = urlopen.requests[0]
            self.assertIn("gemini-3.5-flash-lite:generateContent", request.full_url)
            self.assertNotIn("test-key", request.full_url)  # key goes in a header only
            self.assertEqual(request.get_header("X-goog-api-key"), "test-key")
            parts = json.loads(request.data)["contents"][0]["parts"]
            self.assertEqual(parts[0]["inline_data"]["mime_type"], "image/png")

            self.assertEqual(response["source"], "live")
            self.assertEqual(response["model"], "gemini-3.5-flash-lite")
            self.assertIn("received_at", response)
            self.assertEqual(parse_response(response["raw_text"])["total_cents"], 10000)
            saved_text = (Path(tmp) / "clean.json").read_text()
            self.assertNotIn("test-key", saved_text)

    def test_retries_429_and_503_using_retry_delay(self):
        sleeps = []
        urlopen = FakeUrlopen(429, 503, gemini_reply(FAKE_JSON))
        with tempfile.TemporaryDirectory() as tmp:
            gemini_provider(tmp, urlopen, sleeps).extract("clean", IMAGES_DIR / "clean.png")
        self.assertEqual(len(urlopen.requests), 3)
        self.assertEqual(sleeps, [8.0, 8.0])

    def test_gives_up_after_three_retries(self):
        urlopen = FakeUrlopen(429, 429, 429, 429)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                gemini_provider(tmp, urlopen, []).extract("clean", IMAGES_DIR / "clean.png")
        self.assertEqual(len(urlopen.requests), 4)

    def test_other_http_errors_are_not_retried(self):
        urlopen = FakeUrlopen(400)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                gemini_provider(tmp, urlopen, []).extract("clean", IMAGES_DIR / "clean.png")
        self.assertEqual(len(urlopen.requests), 1)

    def test_truncated_and_blocked_replies_are_labelled(self):
        urlopen = FakeUrlopen(gemini_reply('{"invoice', "MAX_TOKENS"), {"promptFeedback": {"blockReason": "OTHER"}})
        with tempfile.TemporaryDirectory() as tmp:
            provider = gemini_provider(tmp, urlopen, [])
            self.assertEqual(provider.extract("a", IMAGES_DIR / "clean.png")["raw_text"],
                             "(response truncated at max tokens)")
            self.assertEqual(provider.extract("b", IMAGES_DIR / "clean.png")["raw_text"],
                             "(no response from model: OTHER)")

    def test_requests_are_spaced_out(self):
        sleeps = []
        urlopen = FakeUrlopen(gemini_reply("note one"), gemini_reply("note two"))
        provider = GeminiProvider("k", "m", ".", min_interval=30, urlopen=urlopen, sleep=sleeps.append)
        self.assertEqual(provider.draft_note("p"), "note one")
        self.assertEqual(provider.draft_note("p"), "note two")
        self.assertEqual(len(sleeps), 1)
        self.assertGreater(sleeps[0], 29)


if __name__ == "__main__":
    unittest.main()
