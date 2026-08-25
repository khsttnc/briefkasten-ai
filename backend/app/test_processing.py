import json
import unittest
from unittest.mock import patch, MagicMock

from .document_processing import (
    MAX_ANALYSIS_TEXT_CHARS,
    TRUNCATION_HEAD_CHARS,
    TRUNCATION_TAIL_CHARS,
    DocumentProcessingOrchestrator,
    is_text_truncated_for_analysis,
)
from .providers.ollama_provider import OllamaProvider
from .providers.claude_provider import ClaudeProvider
from .ai_service import AIAnalysisResult


class DummyProvider:
    provider_name = 'dummy'
    model_name = 'dummy-model'

    def __init__(self):
        self.calls = 0

    def analyze_document(self, text: str) -> AIAnalysisResult:
        self.calls += 1
        return AIAnalysisResult(
            document_type='invoice',
            language='de',
            summary='Özet',
            turkish_explanation='Açıklama',
            important_dates=['2026-08-08'],
            extracted_entities=[{'name': 'Firma'}],
            raw_response={'document_type': 'invoice', 'language': 'de'},
        )

    def analyze_document_with_task(self, text: str, task: str) -> AIAnalysisResult:
        raise AssertionError('single-call orchestrator must not use analyze_document_with_task')


class TestDocumentProcessingOrchestrator(unittest.TestCase):
    def test_orchestrator_makes_single_provider_call_with_all_fields(self):
        provider = DummyProvider()
        orchestrator = DocumentProcessingOrchestrator(provider)

        result = orchestrator.run('Test text')

        self.assertEqual(provider.calls, 1)
        self.assertEqual(result.document_type, 'invoice')
        self.assertEqual(result.language, 'de')
        self.assertEqual(result.summary, 'Özet')
        self.assertEqual(result.turkish_explanation, 'Açıklama')
        self.assertEqual(result.important_dates, ['2026-08-08'])
        self.assertEqual(result.extracted_entities, [{'name': 'Firma'}])

    def test_orchestrator_propagates_error_from_single_call(self):
        class ErrorProvider(DummyProvider):
            def analyze_document(self, text: str) -> AIAnalysisResult:
                self.calls += 1
                return AIAnalysisResult(error_message='fail')

        provider = ErrorProvider()
        orchestrator = DocumentProcessingOrchestrator(provider)

        result = orchestrator.run('Test text')
        self.assertEqual(result.error_message, 'fail')
        self.assertEqual(provider.calls, 1)


class SpyProvider(DummyProvider):
    """Records the exact text it was called with, so truncation behavior
    can be asserted on what actually reaches the provider."""

    def __init__(self):
        super().__init__()
        self.received_text = None

    def analyze_document(self, text: str) -> AIAnalysisResult:
        self.received_text = text
        return super().analyze_document(text)


class TextTruncationTestCase(unittest.TestCase):
    """Regression test for: a 206,540-character ADAC insurance policy PDF
    was sent to the AI provider in full - expensive and unnecessary, since
    this pipeline's personalized signal (sender, dates, an actionable
    deadline) is almost never buried in hundreds of pages of boilerplate
    terms."""

    def test_short_text_is_sent_unmodified(self):
        provider = SpyProvider()
        text = "short text"
        DocumentProcessingOrchestrator(provider).run(text)
        self.assertEqual(provider.received_text, text)

    def test_text_exactly_at_limit_is_sent_unmodified(self):
        provider = SpyProvider()
        text = "X" * MAX_ANALYSIS_TEXT_CHARS
        DocumentProcessingOrchestrator(provider).run(text)
        self.assertEqual(provider.received_text, text)

    def test_long_text_is_truncated_to_head_and_tail_with_marker(self):
        head = "A" * TRUNCATION_HEAD_CHARS
        middle = "C" * 5000
        tail = "B" * TRUNCATION_TAIL_CHARS
        text = head + middle + tail

        provider = SpyProvider()
        DocumentProcessingOrchestrator(provider).run(text)

        received = provider.received_text
        self.assertLess(len(received), len(text))
        self.assertTrue(received.startswith(head))
        self.assertTrue(received.endswith(tail))
        self.assertIn("SYSTEM NOTE", received)
        self.assertIn(str(len(middle)), received)
        # The omitted middle must actually be gone, not just summarized.
        self.assertNotIn("C" * 100, received)


class IsTextTruncatedForAnalysisTestCase(unittest.TestCase):
    def test_none_character_count_is_not_truncated(self):
        self.assertFalse(is_text_truncated_for_analysis(None))

    def test_under_limit_is_not_truncated(self):
        self.assertFalse(is_text_truncated_for_analysis(100))

    def test_exactly_at_limit_is_not_truncated(self):
        self.assertFalse(is_text_truncated_for_analysis(MAX_ANALYSIS_TEXT_CHARS))

    def test_over_limit_is_truncated(self):
        self.assertTrue(is_text_truncated_for_analysis(MAX_ANALYSIS_TEXT_CHARS + 1))


class TestProviderSelection(unittest.TestCase):
    @patch.dict('os.environ', {'AI_PROVIDER': 'ollama', 'OLLAMA_MODEL': 'test-model'})
    @patch('backend.app.providers.ollama_provider.urllib.request.urlopen')
    def test_provider_factory_selects_ollama(self, mock_urlopen):
        mock_urlopen.return_value = MagicMock()
        from .providers.provider_factory import get_ai_provider

        provider = get_ai_provider()
        self.assertEqual(provider.provider_name, 'ollama')

    @patch.dict('os.environ', {'AI_PROVIDER': 'ollama', 'OLLAMA_MODEL': 'test-model'}, clear=True)
    def test_provider_factory_ollama_does_not_import_anthropic(self):
        from .providers.provider_factory import get_ai_provider

        original_import = __import__

        def import_blocker(name, globals=None, locals=None, fromlist=(), level=0):
            if name == 'anthropic' or name.startswith('anthropic.'):
                raise ImportError('anthropic should not be imported for ollama')
            return original_import(name, globals, locals, fromlist, level)

        with patch('builtins.__import__', side_effect=import_blocker):
            provider = get_ai_provider()

        self.assertEqual(provider.provider_name, 'ollama')
        self.assertEqual(provider.model_name, 'test-model')
        self.assertIsInstance(provider, OllamaProvider)

    @patch.dict('os.environ', {}, clear=True)
    def test_provider_factory_defaults_to_claude(self):
        from .providers.provider_factory import get_ai_provider

        with self.assertRaises(RuntimeError):
            get_ai_provider()


if __name__ == '__main__':
    unittest.main()
