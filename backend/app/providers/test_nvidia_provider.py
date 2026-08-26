import json
import unittest
from unittest.mock import patch, MagicMock
import urllib.error

from .. import document_intelligence
from ..ai_service import AIAnalysisResult
from .nvidia_provider import NvidiaProvider, _build_nvidia_prompt, _load_json_safe


class DummyResponse:
    def __init__(self, text: str):
        self._text = text

    def read(self):
        return self._text.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


def _openai_style_response(content: str, finish_reason: str = "stop") -> str:
    return json.dumps(
        {
            "choices": [
                {
                    "finish_reason": finish_reason,
                    "message": {"content": content},
                }
            ]
        }
    )


class TestLoadJsonSafe(unittest.TestCase):
    def test_valid_json(self):
        self.assertEqual(_load_json_safe('{"a": 1}'), {"a": 1})

    def test_invalid_json(self):
        self.assertIsNone(_load_json_safe('not json'))

    def test_strips_markdown_fence(self):
        parsed = _load_json_safe('```json\n{"a": 1}\n```')
        self.assertEqual(parsed, {"a": 1})

    def test_strips_leading_and_trailing_commentary(self):
        parsed = _load_json_safe('Here you go:\n{"a": 1}\nHope that helps.')
        self.assertEqual(parsed, {"a": 1})

    def test_strips_surrounding_whitespace(self):
        parsed = _load_json_safe('\n\n  {"a": 1}  \n\n')
        self.assertEqual(parsed, {"a": 1})

    def test_still_rejects_garbage_between_braces(self):
        self.assertIsNone(_load_json_safe('prefix { not valid json } suffix'))


class TestNvidiaProvider(unittest.TestCase):
    def test_build_prompt_contains_expected_fields(self):
        prompt = _build_nvidia_prompt("Das ist ein Testdokument.")
        self.assertIn("document_type", prompt)
        self.assertIn("turkish_explanation", prompt)

    def test_build_prompt_requests_every_signal_key(self):
        # Regression guard: the NVIDIA provider reuses the shared
        # signal-aware prompt builder (see nvidia_provider.py) rather than a
        # simplified 6-key prompt, so it must request every
        # document_intelligence.SIGNAL_KEYS entry, same as Ollama.
        prompt = _build_nvidia_prompt("Das ist ein Testdokument.")
        for key in document_intelligence.SIGNAL_KEYS:
            self.assertIn(key, prompt, f"prompt is missing the exact signal key '{key}'")

    @patch.dict("os.environ", {}, clear=True)
    def test_nvidia_provider_requires_api_key(self):
        with self.assertRaises(RuntimeError):
            NvidiaProvider()

    @patch.dict("os.environ", {"NVIDIA_API_KEY": "test-key"})
    @patch("backend.app.providers.nvidia_provider.urllib.request.urlopen")
    def test_nvidia_provider_parses_response(self, mock_urlopen):
        content = json.dumps({
            "document_type": "invoice",
            "language": "de",
            "summary": "Özet",
            "turkish_explanation": "Açıklama",
            "important_dates": ["2026-08-08"],
            "extracted_entities": [{"name": "Firma"}],
        })
        raw_json = json.dumps({"choices": [{"message": {"content": content}}]})
        mock_urlopen.return_value = DummyResponse(raw_json)

        provider = NvidiaProvider()
        result = provider.analyze_document("Test text")

        mock_urlopen.assert_called_once()
        sent_request = mock_urlopen.call_args[0][0]
        self.assertEqual(sent_request.get_header("Authorization"), "Bearer test-key")

        self.assertIsInstance(result, AIAnalysisResult)
        self.assertEqual(result.document_type, "invoice")
        self.assertEqual(result.language, "de")
        self.assertEqual(result.summary, "Özet")
        self.assertEqual(result.turkish_explanation, "Açıklama")
        self.assertEqual(result.important_dates, ["2026-08-08"])
        self.assertEqual(result.extracted_entities, [{"name": "Firma"}])

    @patch.dict("os.environ", {"NVIDIA_API_KEY": "test-key"})
    @patch("backend.app.providers.nvidia_provider.urllib.request.urlopen")
    def test_gpt_oss_default_model_gets_reasoning_effort_not_chat_template_kwargs(
        self, mock_urlopen
    ):
        # Regression guard: chat_template_kwargs.thinking is a nemotron-only
        # NIM chat-template toggle, silently ignored by gpt-oss models (the
        # current default - see config.DEFAULT_NVIDIA_MODEL) - a real API
        # call confirmed it has no effect there. gpt-oss's own reasoning
        # control is the separate reasoning_effort parameter instead.
        content = json.dumps({"document_type": "letter"})
        raw_json = json.dumps({"choices": [{"message": {"content": content}}]})
        mock_urlopen.return_value = DummyResponse(raw_json)

        provider = NvidiaProvider()
        self.assertIn("gpt-oss", provider.model_name)
        provider.analyze_document("Test text")

        sent_request = mock_urlopen.call_args[0][0]
        sent_body = json.loads(sent_request.data)
        self.assertEqual(sent_body.get("reasoning_effort"), "low")
        self.assertNotIn("chat_template_kwargs", sent_body)

    @patch.dict(
        "os.environ", {"NVIDIA_API_KEY": "test-key", "NVIDIA_MODEL": "nvidia/nemotron-3-nano-30b-a3b"}
    )
    @patch("backend.app.providers.nvidia_provider.urllib.request.urlopen")
    def test_nemotron_model_gets_chat_template_kwargs_not_reasoning_effort(self, mock_urlopen):
        content = json.dumps({"document_type": "letter"})
        raw_json = json.dumps({"choices": [{"message": {"content": content}}]})
        mock_urlopen.return_value = DummyResponse(raw_json)

        provider = NvidiaProvider()
        provider.analyze_document("Test text")

        sent_request = mock_urlopen.call_args[0][0]
        sent_body = json.loads(sent_request.data)
        self.assertEqual(sent_body.get("chat_template_kwargs"), {"thinking": False})
        self.assertNotIn("reasoning_effort", sent_body)

    @patch.dict("os.environ", {"NVIDIA_API_KEY": "test-key"})
    @patch("backend.app.providers.nvidia_provider.urllib.request.urlopen")
    def test_nvidia_provider_invalid_json(self, mock_urlopen):
        raw_json = json.dumps({"choices": [{"message": {"content": "not json"}}]})
        mock_urlopen.return_value = DummyResponse(raw_json)

        provider = NvidiaProvider()
        result = provider.analyze_document("Test text")

        self.assertIsNotNone(result.error_message)
        self.assertEqual(result.raw_response["raw_text"], "not json")

    @patch.dict("os.environ", {"NVIDIA_API_KEY": "test-key"})
    @patch("backend.app.providers.nvidia_provider.urllib.request.urlopen")
    def test_nvidia_provider_authentication_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://integrate.api.nvidia.com/v1/chat/completions", 401, "unauthorized", {}, None
        )

        provider = NvidiaProvider()
        result = provider.analyze_document("Test text")

        self.assertIsNotNone(result.error_message)
        self.assertIn("authentication", result.error_message.lower())
        self.assertNotIn("test-key", result.error_message)

    @patch.dict("os.environ", {"NVIDIA_API_KEY": "test-key"})
    @patch("backend.app.providers.nvidia_provider.urllib.request.urlopen")
    def test_nvidia_provider_rate_limit_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://integrate.api.nvidia.com/v1/chat/completions", 429, "rate limited", {}, None
        )

        provider = NvidiaProvider()
        result = provider.analyze_document("Test text")

        self.assertIsNotNone(result.error_message)
        self.assertIn("rate limit", result.error_message.lower())

    @patch.dict("os.environ", {"NVIDIA_API_KEY": "test-key"})
    @patch("backend.app.providers.nvidia_provider.urllib.request.urlopen")
    def test_nvidia_provider_connection_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("connection refused")

        provider = NvidiaProvider()
        result = provider.analyze_document("Test text")

        self.assertIsNotNone(result.error_message)
        self.assertIn("connect", result.error_message.lower())

    @patch.dict("os.environ", {"NVIDIA_API_KEY": "test-key"})
    @patch("backend.app.providers.nvidia_provider.urllib.request.urlopen")
    def test_finish_reason_length_is_a_hard_failure_not_a_partial_parse(self, mock_urlopen):
        # Regression test for a real finding: a 2,000,000-character test
        # document drove completion_tokens to exactly the max_tokens cap in
        # a live API call - the response was cut off, not finished. Even if
        # the truncated content happens to still parse as valid JSON (its
        # braces/strings could coincidentally close right where generation
        # was cut), it must never be used - fail closed on finish_reason
        # alone, before any attempt to read raw_text.
        complete_but_flagged_as_cut = json.dumps({"document_type": "Bescheid"})
        mock_urlopen.return_value = DummyResponse(
            _openai_style_response(complete_but_flagged_as_cut, finish_reason="length")
        )

        provider = NvidiaProvider()
        result = provider.analyze_document("Test text")

        self.assertIsNotNone(result.error_message)
        self.assertIn("cut off", result.error_message)
        self.assertIsNone(result.document_type)

    @patch.dict("os.environ", {"NVIDIA_API_KEY": "test-key"})
    @patch("backend.app.providers.nvidia_provider.urllib.request.urlopen")
    def test_finish_reason_length_with_genuinely_truncated_json_is_also_a_hard_failure(
        self, mock_urlopen
    ):
        truncated_json = '{"document_type": "Bescheid", "summary": "unvoll'
        mock_urlopen.return_value = DummyResponse(
            _openai_style_response(truncated_json, finish_reason="length")
        )

        provider = NvidiaProvider()
        result = provider.analyze_document("Test text")

        self.assertIsNotNone(result.error_message)
        self.assertIn("cut off", result.error_message)

    @patch.dict("os.environ", {"NVIDIA_API_KEY": "test-key"})
    @patch("backend.app.providers.nvidia_provider.urllib.request.urlopen")
    def test_finish_reason_stop_with_valid_json_succeeds(self, mock_urlopen):
        content = json.dumps({"document_type": "Bescheid"})
        mock_urlopen.return_value = DummyResponse(
            _openai_style_response(content, finish_reason="stop")
        )

        provider = NvidiaProvider()
        result = provider.analyze_document("Test text")

        self.assertIsNone(result.error_message)
        self.assertEqual(result.document_type, "Bescheid")

    @patch.dict("os.environ", {"NVIDIA_API_KEY": "test-key"})
    @patch("backend.app.providers.nvidia_provider.urllib.request.urlopen")
    def test_request_sends_max_tokens_with_real_measured_safety_margin(self, mock_urlopen):
        content = json.dumps({"document_type": "Bescheid"})
        mock_urlopen.return_value = DummyResponse(_openai_style_response(content))

        provider = NvidiaProvider()
        provider.analyze_document("Test text")

        sent_request = mock_urlopen.call_args[0][0]
        sent_body = json.loads(sent_request.data.decode("utf-8"))
        # A real test call against the live API with a realistic
        # 500,000-character document used ~570-585 completion tokens before
        # the entity/sentence prompt caps were added, and 438 after (see
        # DEFAULT_MAX_TOKENS's comment in nvidia_provider.py) - this must
        # stay comfortably above both measurements, not just above the old
        # hardcoded value.
        self.assertGreaterEqual(sent_body["max_tokens"], 2000)


if __name__ == "__main__":
    unittest.main()
