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

    def analyze_document(self, text: str) -> AIAnalysisResult:
        return AIAnalysisResult(document_type='invoice', language='de')

    def analyze_document_with_task(self, text: str, task: str) -> AIAnalysisResult:
        if task == 'classification':
            return AIAnalysisResult(document_type='invoice', language='de')
        if task == 'extraction':
            return AIAnalysisResult(important_dates=['2026-08-08'], extracted_entities=[{'name': 'Firma'}])
        if task == 'explanation':
            return AIAnalysisResult(summary='Özet', turkish_explanation='Açıklama')
        return AIAnalysisResult()


class TestDocumentProcessingOrchestrator(unittest.TestCase):
    def test_orchestrator_combines_pipeline_results(self):
        provider = DummyProvider()
        orchestrator = DocumentProcessingOrchestrator(provider)

        result = orchestrator.run('Test text')

        self.assertEqual(result.document_type, 'invoice')
        self.assertEqual(result.language, 'de')
        self.assertEqual(result.summary, 'Özet')
        self.assertEqual(result.turkish_explanation, 'Açıklama')
        self.assertEqual(result.important_dates, ['2026-08-08'])
        self.assertEqual(result.extracted_entities, [{'name': 'Firma'}])
        self.assertIn('classification', result.raw_response)
        self.assertIn('extraction', result.raw_response)
        self.assertIn('explanation', result.raw_response)

    def test_orchestrator_stops_on_error(self):
        class ErrorProvider(DummyProvider):
            def analyze_document_with_task(self, text: str, task: str) -> AIAnalysisResult:
                if task == 'classification':
                    return AIAnalysisResult(error_message='fail')
                return super().analyze_document_with_task(text, task)

        provider = ErrorProvider()
        orchestrator = DocumentProcessingOrchestrator(provider)

        result = orchestrator.run('Test text')
        self.assertEqual(result.error_message, 'fail')


class TestProviderSelection(unittest.TestCase):
    @patch.dict('os.environ', {'AI_PROVIDER': 'ollama', 'OLLAMA_MODEL': 'test-model'})
    @patch('backend.app.providers.ollama_provider.urllib.request.urlopen')
    def test_provider_factory_selects_ollama(self, mock_urlopen):
        mock_urlopen.return_value = MagicMock()
        from .providers.provider_factory import get_ai_provider

        provider = get_ai_provider()
        self.assertEqual(provider.provider_name, 'ollama')

    @patch.dict('os.environ', {}, clear=True)
    def test_provider_factory_defaults_to_claude(self):
        from .providers.provider_factory import get_ai_provider

        with self.assertRaises(RuntimeError):
            get_ai_provider()


if __name__ == '__main__':
    unittest.main()
