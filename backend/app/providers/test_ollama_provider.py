import json
import unittest
from unittest.mock import patch, MagicMock

from ..ai_service import AIAnalysisResult
from . import ollama_provider as ollama_provider_module
from .ollama_provider import OllamaProvider, _build_ollama_prompt


class DummyResponse:
    def __init__(self, text: str):
        self._text = text

    def read(self):
        return self._text.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class TestOllamaProvider(unittest.TestCase):
    @patch.dict('os.environ', {'OLLAMA_MODEL': 'test-model'})
    @patch('backend.app.providers.ollama_provider.urllib.request.urlopen')
    def test_ollama_provider_parses_response(self, mock_urlopen):
        raw_json = json.dumps({
            "results": [{"text": json.dumps({
                "document_type": "invoice",
                "language": "de",
                "summary": "Özet",
                "turkish_explanation": "Açıklama",
                "important_dates": ["2026-08-08"],
                "extracted_entities": [{"name": "Firma"}],
            })}]
        })
        mock_urlopen.return_value = DummyResponse(raw_json)

        provider = OllamaProvider()
        result = provider.analyze_document('Test text')

        mock_urlopen.assert_called_once()

        self.assertIsInstance(result, AIAnalysisResult)
        self.assertEqual(result.document_type, 'invoice')
        self.assertEqual(result.language, 'de')
        self.assertEqual(result.summary, 'Özet')
        self.assertEqual(result.turkish_explanation, 'Açıklama')
        self.assertEqual(result.important_dates, ['2026-08-08'])
        self.assertEqual(result.extracted_entities, [{'name': 'Firma'}])

    @patch.dict('os.environ', {'OLLAMA_MODEL': 'test-model'})
    @patch('backend.app.providers.ollama_provider.urllib.request.urlopen')
    def test_ollama_provider_invalid_json(self, mock_urlopen):
        mock_urlopen.return_value = DummyResponse('not json')

        provider = OllamaProvider()
        result = provider.analyze_document('Test text')

        self.assertIsNotNone(result.error_message)
        self.assertEqual(result.raw_response['raw_text'], 'not json')

    @patch.dict('os.environ', {})
    def test_ollama_provider_requires_model_env(self):
        with self.assertRaises(RuntimeError):
            OllamaProvider()

    @patch.dict('os.environ', {'OLLAMA_MODEL': 'test-model'})
    @patch('backend.app.providers.ollama_provider.urllib.request.urlopen')
    def test_ollama_provider_handles_missing_turkish_explanation(self, mock_urlopen):
        # Regression guard: some small models omit or null out a field they
        # weren't given clear enough instructions to fill in. The provider
        # must still surface the other fields instead of erroring out.
        raw_json = json.dumps({
            "results": [{"text": json.dumps({
                "document_type": "invoice",
                "language": "de",
                "summary": "Özet",
                "turkish_explanation": None,
                "important_dates": [],
                "extracted_entities": [],
            })}]
        })
        mock_urlopen.return_value = DummyResponse(raw_json)

        provider = OllamaProvider()
        result = provider.analyze_document('Test text')

        self.assertIsNone(result.error_message)
        self.assertEqual(result.document_type, 'invoice')
        self.assertEqual(result.summary, 'Özet')
        self.assertIsNone(result.turkish_explanation)


class TestOllamaGenerationSettings(unittest.TestCase):
    """Regression guard for the generation-stability fix: the request body
    sent to Ollama's native /api/generate must use options.num_predict (the
    parameter Ollama actually understands) instead of the no-op top-level
    max_tokens field, and must carry conservative sampling settings so a
    small model like llama3.2:3b doesn't drift into repetition loops or
    malformed JSON."""

    @patch.dict('os.environ', {'OLLAMA_MODEL': 'test-model'})
    @patch('backend.app.providers.ollama_provider.urllib.request.urlopen')
    def _send_and_capture_body(self, mock_urlopen):
        raw_json = json.dumps({"response": json.dumps({"document_type": "letter"})})
        mock_urlopen.return_value = DummyResponse(raw_json)

        provider = OllamaProvider()
        provider.analyze_document('Test text')

        sent_request = mock_urlopen.call_args[0][0]
        return json.loads(sent_request.data.decode('utf-8'))

    def test_request_does_not_send_unsupported_max_tokens_field(self):
        body = self._send_and_capture_body()
        self.assertNotIn('max_tokens', body)

    def test_request_sends_num_predict_via_options(self):
        body = self._send_and_capture_body()
        self.assertIn('options', body)
        self.assertEqual(body['options']['num_predict'], ollama_provider_module.DEFAULT_NUM_PREDICT)

    def test_request_sends_expected_generation_options(self):
        body = self._send_and_capture_body()
        options = body['options']
        self.assertEqual(options['num_ctx'], ollama_provider_module.DEFAULT_NUM_CTX)
        self.assertEqual(options['temperature'], ollama_provider_module.DEFAULT_TEMPERATURE)
        self.assertEqual(options['repeat_penalty'], ollama_provider_module.DEFAULT_REPEAT_PENALTY)

    def test_request_uses_non_streaming_json_format(self):
        body = self._send_and_capture_body()
        self.assertEqual(body['stream'], False)
        self.assertEqual(body['format'], 'json')


class TestBuildOllamaPrompt(unittest.TestCase):
    """Regression guard for the audit finding: the Ollama prompt must
    explicitly instruct the model to write turkish_explanation in Turkish,
    the way the Claude provider's prompt already does. Without this
    instruction, small models like llama3.2:3b tend to leave the field
    empty or null since the key name alone isn't a reliable enough signal."""

    def test_default_prompt_instructs_turkish_explanation_in_turkish(self):
        prompt = _build_ollama_prompt("Some German document text", task=None)

        self.assertIn("turkish_explanation", prompt)
        self.assertIn("TURKISH", prompt)
        self.assertIn("consequences", prompt)
        self.assertIn("what the reader should do next", prompt)

    def test_explanation_task_prompt_instructs_turkish_explanation_in_turkish(self):
        prompt = _build_ollama_prompt("Some German document text", task="explanation")

        self.assertIn("turkish_explanation", prompt)
        self.assertIn("TURKISH", prompt)
        self.assertIn("what the reader should do next", prompt)

    def test_classification_and_extraction_prompts_unchanged(self):
        # Scope guard: only the summary/turkish_explanation-bearing prompts
        # should mention Turkish; the other two tasks don't touch that field.
        classification_prompt = _build_ollama_prompt("text", task="classification")
        extraction_prompt = _build_ollama_prompt("text", task="extraction")

        self.assertNotIn("TURKISH", classification_prompt)
        self.assertNotIn("TURKISH", extraction_prompt)


if __name__ == '__main__':
    unittest.main()
