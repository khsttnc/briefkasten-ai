import json
import unittest
from unittest.mock import patch

from ..ai_service import AIAnalysisResult
from .claude_provider import ClaudeProvider, _build_claude_prompt, _load_json_safe


class DummyResponse:
    def __init__(self, content: str):
        self.content = [{"type": "text", "text": content}]


class TestClaudeProvider(unittest.TestCase):
    def test_build_prompt_contains_expected_fields(self):
        prompt = _build_claude_prompt('Das ist ein Testdokument.')
        self.assertIn('document_type', prompt)
        self.assertIn('turkish_explanation', prompt)
        self.assertIn('Important entities', prompt)

    def test_load_json_safe_valid(self):
        text = '{"document_type": "contract", "language": "de"}'
        parsed = _load_json_safe(text)
        self.assertEqual(parsed['document_type'], 'contract')
        self.assertEqual(parsed['language'], 'de')

    def test_load_json_safe_invalid(self):
        self.assertIsNone(_load_json_safe('not json'))

    @patch('backend.app.providers.claude_provider.Anthropic')
    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'})
    def test_claude_provider_parses_response(self, mock_anthropic):
        returned_text = '{"document_type": "invoice", "language": "de", "summary": "Özet", "turkish_explanation": "Açıklama", "important_dates": ["2026-08-08"], "extracted_entities": [{"name": "Firma"}]}'
        mock_anthropic.return_value.messages.create.return_value = DummyResponse(returned_text)

        provider = ClaudeProvider()
        result = provider.analyze_document('Test text')

        mock_anthropic.return_value.messages.create.assert_called_once()
        call_kwargs = mock_anthropic.return_value.messages.create.call_args.kwargs
        self.assertNotIn('stop_sequences', call_kwargs)

        self.assertIsInstance(result, AIAnalysisResult)
        self.assertEqual(result.document_type, 'invoice')
        self.assertEqual(result.language, 'de')
        self.assertEqual(result.summary, 'Özet')
        self.assertEqual(result.turkish_explanation, 'Açıklama')
        self.assertEqual(result.important_dates, ['2026-08-08'])
        self.assertEqual(result.extracted_entities, [{'name': 'Firma'}])

    @patch('backend.app.providers.claude_provider.Anthropic')
    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'})
    def test_claude_provider_invalid_json(self, mock_anthropic):
        mock_anthropic.return_value.messages.create.return_value = DummyResponse('not json')

        provider = ClaudeProvider()
        result = provider.analyze_document('Test text')

        self.assertIsNotNone(result.error_message)
        self.assertEqual(result.raw_response['raw_text'], 'not json')


if __name__ == '__main__':
    unittest.main()
