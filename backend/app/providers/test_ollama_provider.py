import json
import unittest
from unittest.mock import patch, MagicMock

from .. import document_intelligence
from ..ai_service import AIAnalysisResult
from . import ollama_provider as ollama_provider_module
from .ollama_provider import OllamaProvider, _build_ollama_prompt, _load_json_safe


class DummyResponse:
    def __init__(self, text: str):
        self._text = text

    def read(self):
        return self._text.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


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
    def test_ollama_provider_mid_response_timeout_is_handled_cleanly(self, mock_urlopen):
        # Regression guard: observed in real testing against qwen3:8b - a
        # timeout that happens mid-response (inside getresponse()/read(),
        # after the connection succeeded) raises a bare TimeoutError, not
        # urllib.error.URLError. Before the fix this propagated all the way
        # out of analyze_document() uncaught, which would have crashed the
        # analyze endpoint instead of producing a clean failed analysis.
        mock_urlopen.side_effect = TimeoutError("timed out")

        provider = OllamaProvider()
        result = provider.analyze_document('Test text')

        self.assertIsNotNone(result.error_message)
        self.assertIn('timed out', result.error_message)

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

    def test_possible_multiple_documents_hint_absent_by_default(self):
        prompt = _build_ollama_prompt("Some German document text")
        self.assertNotIn("more than one separate document", prompt)

    def test_possible_multiple_documents_hint_added_when_flagged(self):
        prompt = _build_ollama_prompt(
            "Some German document text", possible_multiple_documents=True
        )
        self.assertIn("more than one separate document", prompt)
        self.assertIn("important_dates", prompt)
        self.assertIn(document_intelligence.MULTIPLE_DEADLINES_DETECTED_KEY, prompt)

    def test_possible_multiple_documents_hint_only_applies_to_default_prompt(self):
        # The task-specific mini-prompts have no schema field for this hint
        # to feed into (see AIService.analyze) - confirm the builder itself
        # doesn't add it to those even if asked to.
        for task in ("classification", "extraction", "explanation"):
            prompt = _build_ollama_prompt("text", task=task, possible_multiple_documents=True)
            self.assertNotIn("more than one separate document", prompt)

    def test_classification_and_extraction_prompts_unchanged(self):
        # Scope guard: only the summary/turkish_explanation-bearing prompts
        # should mention Turkish; the other two tasks don't touch that field.
        classification_prompt = _build_ollama_prompt("text", task="classification")
        extraction_prompt = _build_ollama_prompt("text", task="extraction")

        self.assertNotIn("TURKISH", classification_prompt)
        self.assertNotIn("TURKISH", extraction_prompt)

    def test_default_prompt_forbids_leaking_boolean_signals_into_explanation(self):
        # Regression guard for a real production output: turkish_explanation
        # contained garbled sentences like "Odeme talebi edilmez" (no payment
        # requested) and "Coklu son verisi bulunmamaktadir" (no multiple
        # deadlines) - the model was narrating the boolean signal fields
        # instead of just describing the document. The default prompt is the
        # only one that requests both turkish_explanation and the signal
        # keys together (see DocumentIntelligenceSignalKeysTestCase above),
        # so it's the only one that needs this instruction.
        prompt = _build_ollama_prompt("Some German document text", task=None)

        self.assertIn(document_intelligence.PAYMENT_REQUESTED_KEY, prompt)
        self.assertIn(document_intelligence.OBJECTION_RIGHT_KEY, prompt)
        self.assertIn(document_intelligence.MULTIPLE_DEADLINES_DETECTED_KEY, prompt)
        self.assertIn("must NEVER mention, name, or restate", prompt)
        self.assertIn("does not apply", prompt)


class DocumentIntelligenceSignalKeysTestCase(unittest.TestCase):
    """Regression guard for the exact failure mode flagged during review: a
    typo'd key name in the prompt would still pass every test that only
    checks the prompt in isolation, while silently making
    derive_intelligence_fields() always fall back to its safe low/unknown
    default in real use. These tests import the actual
    document_intelligence.SIGNAL_KEYS constants (the same ones
    derive_intelligence_fields reads raw_response by) instead of retyping
    the key names, so a rename on either side fails this test rather than
    drifting silently."""

    def test_default_prompt_requests_every_signal_key_by_its_exact_name(self):
        prompt = _build_ollama_prompt("Some German document text", task=None)
        for key in document_intelligence.SIGNAL_KEYS:
            self.assertIn(key, prompt, f"prompt is missing the exact signal key '{key}'")

    def test_task_specific_prompts_do_not_need_signal_keys(self):
        # classification/extraction/explanation are split sub-prompts not
        # used by the live single-call pipeline (see
        # DocumentProcessingOrchestrator.run) - documenting the current
        # scope, not a requirement that they carry these keys too.
        for task in ("classification", "extraction", "explanation"):
            prompt = _build_ollama_prompt("text", task=task)
            self.assertNotIn(document_intelligence.CLASSIFIED_DOCUMENT_TYPE_KEY, prompt)

    def test_prompt_prioritizes_objection_deadline_over_payment_deadline(self):
        # Option A fix (review): when multiple deadlines are present, the
        # prompt must tell the model to always pick the
        # objection/appeal deadline over a payment deadline for
        # deadline_raw_text - a silently-picked deadline is exactly the
        # bug being guarded against here.
        prompt = _build_ollama_prompt("Some German document text", task=None)
        self.assertIn(document_intelligence.MULTIPLE_DEADLINES_DETECTED_KEY, prompt)
        self.assertIn("Widerspruch", prompt)
        self.assertIn("outranks a payment deadline", prompt)


if __name__ == '__main__':
    unittest.main()
