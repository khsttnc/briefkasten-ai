import json
import unittest
from unittest.mock import patch

import httpx
from anthropic import (
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    RateLimitError,
)

from ..ai_service import AIAnalysisResult
from .claude_provider import ClaudeProvider, _build_claude_prompt, _load_json_safe


class DummyResponse:
    def __init__(self, content: str):
        self.content = [{"type": "text", "text": content}]


def _httpx_response(status_code: int, body: dict) -> httpx.Response:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return httpx.Response(status_code, request=request, json=body)


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

    def test_load_json_safe_strips_markdown_fence(self):
        text = '```json\n{"document_type": "contract"}\n```'
        parsed = _load_json_safe(text)
        self.assertEqual(parsed['document_type'], 'contract')

    def test_load_json_safe_strips_plain_fence(self):
        text = '```\n{"document_type": "contract"}\n```'
        parsed = _load_json_safe(text)
        self.assertEqual(parsed['document_type'], 'contract')

    def test_load_json_safe_strips_leading_and_trailing_commentary(self):
        text = 'Here is the JSON:\n{"document_type": "contract"}\nLet me know if you need more.'
        parsed = _load_json_safe(text)
        self.assertEqual(parsed['document_type'], 'contract')

    def test_load_json_safe_strips_surrounding_whitespace(self):
        text = '\n\n  {"document_type": "contract"}  \n\n'
        parsed = _load_json_safe(text)
        self.assertEqual(parsed['document_type'], 'contract')

    def test_load_json_safe_still_rejects_garbage_between_braces(self):
        self.assertIsNone(_load_json_safe('prefix { not valid json } suffix'))

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

    @patch('backend.app.providers.claude_provider.Anthropic')
    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'})
    def test_claude_provider_rate_limit_error(self, mock_anthropic):
        response = _httpx_response(429, {'type': 'error', 'error': {'type': 'rate_limit_error', 'message': 'rate limited'}})
        mock_anthropic.return_value.messages.create.side_effect = RateLimitError(
            'rate limited', response=response, body=None
        )

        provider = ClaudeProvider()
        result = provider.analyze_document('Test text')

        self.assertIsInstance(result, AIAnalysisResult)
        self.assertIsNotNone(result.error_message)
        self.assertIn('rate limit', result.error_message.lower())
        self.assertIsNone(result.document_type)
        self.assertNotIn('test-key', result.error_message)

    @patch('backend.app.providers.claude_provider.Anthropic')
    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'})
    def test_claude_provider_authentication_error(self, mock_anthropic):
        response = _httpx_response(401, {'type': 'error', 'error': {'type': 'authentication_error', 'message': 'invalid x-api-key'}})
        mock_anthropic.return_value.messages.create.side_effect = AuthenticationError(
            'invalid x-api-key', response=response, body=None
        )

        provider = ClaudeProvider()
        result = provider.analyze_document('Test text')

        self.assertIsNotNone(result.error_message)
        self.assertIn('authentication', result.error_message.lower())
        self.assertIsNone(result.document_type)
        self.assertNotIn('test-key', result.error_message)

    @patch('backend.app.providers.claude_provider.Anthropic')
    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'})
    def test_claude_provider_connection_error(self, mock_anthropic):
        request = httpx.Request('POST', 'https://api.anthropic.com/v1/messages')
        mock_anthropic.return_value.messages.create.side_effect = APIConnectionError(request=request)

        provider = ClaudeProvider()
        result = provider.analyze_document('Test text')

        self.assertIsNotNone(result.error_message)
        self.assertIn('connect', result.error_message.lower())
        self.assertIsNone(result.document_type)

    @patch('backend.app.providers.claude_provider.Anthropic')
    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'})
    def test_claude_provider_server_error(self, mock_anthropic):
        response = _httpx_response(500, {'type': 'error', 'error': {'type': 'api_error', 'message': 'internal server error'}})
        mock_anthropic.return_value.messages.create.side_effect = APIStatusError(
            'internal server error', response=response, body=None
        )

        provider = ClaudeProvider()
        result = provider.analyze_document('Test text')

        self.assertIsNotNone(result.error_message)
        self.assertIn('500', result.error_message)
        self.assertIsNone(result.document_type)


if __name__ == '__main__':
    unittest.main()
