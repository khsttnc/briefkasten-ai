import json
import unittest
from unittest.mock import patch, MagicMock

from .document_processing import DocumentProcessingOrchestrator
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
