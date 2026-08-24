import json
import unittest
from unittest.mock import patch, MagicMock
import urllib.error

from .. import document_intelligence
from ..ai_service import AIAnalysisResult
from .nvidia_provider import NvidiaProvider, _build_nvidia_prompt


class DummyResponse:
    def __init__(self, text: str):
        self._text = text

    def read(self):
        return self._text.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


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


if __name__ == "__main__":
    unittest.main()
