import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from . import services
from .ai_service import AIAnalysisResult
from .models import Base, Document, DocumentAIAnalysis, User


def _create_test_user(db, external_auth_id: str = "test-user") -> User:
    user = User(external_auth_id=external_auth_id, email=f"{external_auth_id}@example.com")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class FakeUploadFile:
    def __init__(self, filename: str, content: bytes):
        self.filename = filename
        self.file = io.BytesIO(content)


class DummyAIProvider:
    """Stand-in AI provider so no real Claude/Ollama call happens in tests."""

    provider_name = "dummy"
    model_name = "dummy-model"

    def __init__(self):
        self.received_text = None
        self.calls = 0

    def analyze_document(self, text: str) -> AIAnalysisResult:
        self.calls += 1
        self.received_text = text
        return AIAnalysisResult(
            document_type="letter",
            language="de",
            summary="Test summary",
            turkish_explanation="Test aciklama",
            important_dates=["2026-01-01"],
            extracted_entities=[{"name": "Test GmbH"}],
            raw_response={"document_type": "letter"},
        )


class ErrorAIProvider:
    """Stand-in AI provider that always reports a failed analysis, without
    ever making a real Claude/Ollama network call."""

    provider_name = "dummy-error"
    model_name = "dummy-error-model"

    def __init__(self):
        self.calls = 0

    def analyze_document(self, text: str) -> AIAnalysisResult:
        self.calls += 1
        return AIAnalysisResult(
            error_message="Simulated provider failure.",
            raw_response={"raw_text": ""},
        )


def _build_sample_pdf_bytes(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


class UploadAnalyzePipelineIntegrationTestCase(unittest.TestCase):
    """Exercises upload -> document created -> text extraction -> AI provider
    -> analysis result end to end, using an isolated in-memory database, an
    isolated temp upload directory, and a mocked AI provider (no real
    Claude/Ollama network calls). The real backend/briefkasten.db and
    backend/uploads/ are never touched."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="briefkasten_pipeline_test_"))
        self.upload_root_patcher = patch.object(services, "UPLOAD_ROOT", self.tmp_dir.resolve())
        self.upload_root_patcher.start()

        # Isolated in-memory database - completely separate from the app's
        # real SQLAlchemy engine/session bound to backend/briefkasten.db.
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.db = self.SessionLocal()
        self.owner_id = _create_test_user(self.db).id

    def tearDown(self):
        self.db.close()
        self.upload_root_patcher.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_full_pipeline_upload_extract_analyze(self):
        pdf_bytes = _build_sample_pdf_bytes("Rechnung Nr. 123 fuer Test GmbH")
        upload = FakeUploadFile("Rechnung.pdf", pdf_bytes)

        document = services.save_document(upload, self.db, owner_id=self.owner_id)
        self.assertIsNotNone(document.id)
        self.assertEqual(document.status, "uploaded")

        extraction = services.analyze_document_by_id(document.id, self.db, owner_id=self.owner_id)
        self.assertIn("Rechnung", extraction["text"])
        refreshed = self.db.query(Document).filter(Document.id == document.id).first()
        self.assertEqual(refreshed.status, "analyzed")
        self.assertGreater(refreshed.character_count, 0)

        dummy_provider = DummyAIProvider()
        with patch.object(services, "get_ai_provider", return_value=dummy_provider):
            result = services.analyze_document_ai_by_id(document.id, self.db, owner_id=self.owner_id)

        self.assertEqual(dummy_provider.calls, 1)
        self.assertIn("Rechnung", dummy_provider.received_text)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["document_type"], "letter")
        self.assertEqual(result["summary"], "Test summary")
        self.assertIsNone(result["error_message"])


class DuplicateAIAnalysisPreventionTestCase(unittest.TestCase):
    """Verifies that a completed AI analysis is reused instead of re-calling
    the AI provider, while a failed analysis remains retryable. Uses an
    isolated in-memory database, an isolated temp upload directory, and
    mocked AI providers (no real Claude/Ollama network calls). The real
    backend/briefkasten.db and backend/uploads/ are never touched."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="briefkasten_dedupe_test_"))
        self.upload_root_patcher = patch.object(services, "UPLOAD_ROOT", self.tmp_dir.resolve())
        self.upload_root_patcher.start()

        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.db = self.SessionLocal()
        self.owner_id = _create_test_user(self.db).id

    def tearDown(self):
        self.db.close()
        self.upload_root_patcher.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _upload_and_extract(self) -> Document:
        pdf_bytes = _build_sample_pdf_bytes("Bescheid Nr. 456 fuer Test GmbH")
        upload = FakeUploadFile("Bescheid.pdf", pdf_bytes)
        document = services.save_document(upload, self.db, owner_id=self.owner_id)
        services.analyze_document_by_id(document.id, self.db, owner_id=self.owner_id)
        return document

    def test_first_call_invokes_provider_once_and_persists_result(self):
        # Covers: a document with no existing analysis behaves as before -
        # exactly one provider call, exactly one persisted analysis row.
        document = self._upload_and_extract()
        dummy_provider = DummyAIProvider()

        with patch.object(services, "get_ai_provider", return_value=dummy_provider):
            result = services.analyze_document_ai_by_id(document.id, self.db, owner_id=self.owner_id)

        self.assertEqual(dummy_provider.calls, 1)
        self.assertEqual(result["status"], "completed")

        stored = (
            self.db.query(DocumentAIAnalysis)
            .filter(DocumentAIAnalysis.document_id == document.id)
            .all()
        )
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].status, "completed")

    def test_second_call_reuses_cached_result_without_calling_provider(self):
        document = self._upload_and_extract()
        dummy_provider = DummyAIProvider()

        with patch.object(services, "get_ai_provider", return_value=dummy_provider):
            first_result = services.analyze_document_ai_by_id(document.id, self.db, owner_id=self.owner_id)
            second_result = services.analyze_document_ai_by_id(document.id, self.db, owner_id=self.owner_id)

        self.assertEqual(dummy_provider.calls, 1)
        self.assertEqual(second_result, first_result)

        stored = (
            self.db.query(DocumentAIAnalysis)
            .filter(DocumentAIAnalysis.document_id == document.id)
            .all()
        )
        self.assertEqual(len(stored), 1)

    def test_cached_result_preserves_all_fields(self):
        document = self._upload_and_extract()
        dummy_provider = DummyAIProvider()

        with patch.object(services, "get_ai_provider", return_value=dummy_provider):
            services.analyze_document_ai_by_id(document.id, self.db, owner_id=self.owner_id)
            cached_result = services.analyze_document_ai_by_id(document.id, self.db, owner_id=self.owner_id)

        self.assertEqual(dummy_provider.calls, 1)
        self.assertEqual(cached_result["document_type"], "letter")
        self.assertEqual(cached_result["language"], "de")
        self.assertEqual(cached_result["summary"], "Test summary")
        self.assertEqual(cached_result["turkish_explanation"], "Test aciklama")
        self.assertEqual(cached_result["important_dates"], ["2026-01-01"])
        self.assertEqual(cached_result["extracted_entities"], [{"name": "Test GmbH"}])
        self.assertIsNone(cached_result["error_message"])

    def test_failed_analysis_can_be_retried(self):
        document = self._upload_and_extract()
        error_provider = ErrorAIProvider()

        with patch.object(services, "get_ai_provider", return_value=error_provider):
            with self.assertRaises(HTTPException):
                services.analyze_document_ai_by_id(document.id, self.db, owner_id=self.owner_id)

        self.assertEqual(error_provider.calls, 1)

        failed_rows = (
            self.db.query(DocumentAIAnalysis)
            .filter(
                DocumentAIAnalysis.document_id == document.id,
                DocumentAIAnalysis.status == "failed",
            )
            .all()
        )
        self.assertEqual(len(failed_rows), 1)

        dummy_provider = DummyAIProvider()
        with patch.object(services, "get_ai_provider", return_value=dummy_provider):
            result = services.analyze_document_ai_by_id(document.id, self.db, owner_id=self.owner_id)

        self.assertEqual(dummy_provider.calls, 1)
        self.assertEqual(result["status"], "completed")


class DocumentAnalysisErrorHandlingTestCase(unittest.TestCase):
    """Verifies that a corrupted on-disk file and a missing Tesseract binary
    produce clean HTTPExceptions instead of crashing the request."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="briefkasten_analysis_errors_test_"))
        self.upload_root_patcher = patch.object(services, "UPLOAD_ROOT", self.tmp_dir.resolve())
        self.upload_root_patcher.start()

        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.db = self.SessionLocal()
        self.owner_id = _create_test_user(self.db).id

    def tearDown(self):
        self.db.close()
        self.upload_root_patcher.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_corrupt_file_on_disk_raises_clean_error(self):
        pdf_bytes = _build_sample_pdf_bytes("Bescheid Nr. 789")
        document = services.save_document(FakeUploadFile("Bescheid.pdf", pdf_bytes), self.db, owner_id=self.owner_id)

        # Simulate the stored file becoming corrupted after a valid upload.
        with open(document.filepath, "wb") as corrupt_file:
            corrupt_file.write(b"not a pdf anymore")

        with self.assertRaises(HTTPException) as ctx:
            services.analyze_document_by_id(document.id, self.db, owner_id=self.owner_id)

        self.assertEqual(ctx.exception.status_code, 422)

    def test_missing_tesseract_binary_raises_clean_error(self):
        # Empty-text PDF triggers the OCR fallback path.
        pdf_bytes = _build_sample_pdf_bytes("")
        document = services.save_document(
            FakeUploadFile("Scan.pdf", pdf_bytes), self.db, owner_id=self.owner_id
        )

        with patch.object(
            services.pytesseract,
            "image_to_string",
            side_effect=services.pytesseract.TesseractNotFoundError(),
        ):
            with self.assertRaises(HTTPException) as ctx:
                services.analyze_document_by_id(document.id, self.db, owner_id=self.owner_id)

        self.assertEqual(ctx.exception.status_code, 503)


class CorruptedEntityAIProvider:
    """Stand-in AI provider that returns a mix of verifiable and unverifiable
    code/number entities, simulating the qwen3:8b digit-corruption failure
    mode observed in production (see entity_validation.py)."""

    provider_name = "dummy-corrupted-entities"
    model_name = "dummy-corrupted-entities-model"

    def __init__(self):
        self.calls = 0

    def analyze_document(self, text: str) -> AIAnalysisResult:
        self.calls += 1
        return AIAnalysisResult(
            document_type="letter",
            language="de",
            summary="Test summary",
            turkish_explanation="Test aciklama",
            important_dates=["2026-01-01"],
            extracted_entities=[
                # Correct - present verbatim in the uploaded text below.
                {"type": "policy_or_contract_number", "value": "AD-9990001111"},
                # Corrupted - one digit dropped relative to the source.
                {"type": "adac_membership_number", "value": "73433034"},
                # Reformatted, not corrupted - digits/letters unchanged, only
                # separators differ, so this must survive validation.
                {"type": "license_plate", "value": "BEZL37"},
                # Out of scope for validation - must pass through untouched.
                {"type": "customer_name", "value": "Kubilay Anything"},
            ],
            raw_response={"document_type": "letter"},
        )


class EntityValidationPipelineIntegrationTestCase(unittest.TestCase):
    """End-to-end regression guard: a corrupted code/number entity returned
    by the AI provider must be absent from both the persisted DB row and the
    API response, while verifiable entities (including reformatted-but-
    correct ones) and out-of-scope entity types are preserved. Uses an
    isolated in-memory database and temp upload directory - the real
    backend/briefkasten.db and backend/uploads/ are never touched."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="briefkasten_entity_validation_test_"))
        self.upload_root_patcher = patch.object(services, "UPLOAD_ROOT", self.tmp_dir.resolve())
        self.upload_root_patcher.start()

        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.db = self.SessionLocal()
        self.owner_id = _create_test_user(self.db).id

    def tearDown(self):
        self.db.close()
        self.upload_root_patcher.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_corrupted_entity_dropped_verifiable_entities_kept_in_db_and_response(self):
        pdf_bytes = _build_sample_pdf_bytes(
            "Vertrag AD-9990001111 Kennzeichen BE-ZL 37 ADAC-Mitgliedsnummer 734333034"
        )
        document = services.save_document(
            FakeUploadFile("Vertrag.pdf", pdf_bytes), self.db, owner_id=self.owner_id
        )
        services.analyze_document_by_id(document.id, self.db, owner_id=self.owner_id)

        provider = CorruptedEntityAIProvider()
        with patch.object(services, "get_ai_provider", return_value=provider):
            result = services.analyze_document_ai_by_id(document.id, self.db, owner_id=self.owner_id)

        self.assertEqual(provider.calls, 1)

        expected_entities = [
            {"type": "policy_or_contract_number", "value": "AD-9990001111"},
            {"type": "license_plate", "value": "BEZL37"},
            {"type": "customer_name", "value": "Kubilay Anything"},
        ]
        self.assertEqual(result["extracted_entities"], expected_entities)

        stored = (
            self.db.query(DocumentAIAnalysis)
            .filter(DocumentAIAnalysis.document_id == document.id)
            .one()
        )
        self.assertEqual(json.loads(stored.extracted_entities), expected_entities)


class DocumentIntelligencePostProcessingTestCase(unittest.TestCase):
    """Verifies the Step 3 wiring: the priority/deadline engines run after a
    successful or failed AI analysis and populate Document, but can never
    take the analyze pipeline down - even a completely broken
    derive_intelligence_fields must still let the existing response/
    HTTPException behavior through unchanged. Uses an isolated in-memory
    database and temp upload directory - the real backend/briefkasten.db and
    backend/uploads/ are never touched."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="briefkasten_doc_intelligence_test_"))
        self.upload_root_patcher = patch.object(services, "UPLOAD_ROOT", self.tmp_dir.resolve())
        self.upload_root_patcher.start()

        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.db = self.SessionLocal()
        self.owner_id = _create_test_user(self.db).id

    def tearDown(self):
        self.db.close()
        self.upload_root_patcher.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _upload_and_extract(self, text: str = "Bescheid Nr. 999 fuer Test GmbH") -> Document:
        pdf_bytes = _build_sample_pdf_bytes(text)
        upload = FakeUploadFile("Bescheid.pdf", pdf_bytes)
        document = services.save_document(upload, self.db, owner_id=self.owner_id)
        services.analyze_document_by_id(document.id, self.db, owner_id=self.owner_id)
        return document

    def test_successful_analysis_without_signal_keys_gets_safe_default_fields(self):
        # DummyAIProvider's raw_response has no Document Intelligence signal
        # keys yet (the prompt update is a later step) - must not crash, and
        # must populate the safe-default fields rather than leave garbage.
        document = self._upload_and_extract()
        dummy_provider = DummyAIProvider()

        with patch.object(services, "get_ai_provider", return_value=dummy_provider):
            result = services.analyze_document_ai_by_id(document.id, self.db, owner_id=self.owner_id)

        self.assertEqual(result["status"], "completed")

        refreshed = self.db.query(Document).filter(Document.id == document.id).first()
        self.assertEqual(refreshed.deadline_type, "none")
        self.assertEqual(refreshed.deadline_certainty, "exact")
        self.assertEqual(refreshed.priority_level, "low")
        self.assertFalse(refreshed.requires_action)

    def test_failed_analysis_still_raises_and_still_gets_safe_default_fields(self):
        # A failed LLM analysis is exactly the case Step 3 was asked to
        # handle: the existing 502 behavior must be unaffected, and the
        # engines must still run safely on the (signal-less) raw_response.
        document = self._upload_and_extract()
        error_provider = ErrorAIProvider()

        with patch.object(services, "get_ai_provider", return_value=error_provider):
            with self.assertRaises(HTTPException) as ctx:
                services.analyze_document_ai_by_id(document.id, self.db, owner_id=self.owner_id)

        self.assertEqual(ctx.exception.status_code, 502)

        refreshed = self.db.query(Document).filter(Document.id == document.id).first()
        self.assertEqual(refreshed.deadline_type, "none")
        self.assertEqual(refreshed.priority_level, "low")

    def test_broken_intelligence_post_processing_does_not_break_the_pipeline(self):
        # Simulates a completely broken post-processing step (e.g. a future
        # engine regression) - the analyze endpoint must still return its
        # normal, successful response.
        document = self._upload_and_extract()
        dummy_provider = DummyAIProvider()

        with patch.object(services, "get_ai_provider", return_value=dummy_provider), patch.object(
            services, "derive_intelligence_fields", side_effect=RuntimeError("engine exploded")
        ):
            result = services.analyze_document_ai_by_id(document.id, self.db, owner_id=self.owner_id)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["summary"], "Test summary")

        # Post-processing failed and rolled back - fields stay unset rather
        # than the pipeline erroring out.
        refreshed = self.db.query(Document).filter(Document.id == document.id).first()
        self.assertIsNone(refreshed.priority_level)


if __name__ == "__main__":
    unittest.main()
