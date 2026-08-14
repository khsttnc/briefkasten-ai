import json
import unittest
from unittest.mock import patch, MagicMock

from ..ai_service import AIAnalysisResult
from .ollama_provider import OllamaProvider


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


if __name__ == '__main__':
    unittest.main()
