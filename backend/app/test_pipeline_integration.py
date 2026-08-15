import io
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from . import services
from .ai_service import AIAnalysisResult
from .models import Base, Document


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

    def tearDown(self):
        self.db.close()
        self.upload_root_patcher.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_full_pipeline_upload_extract_analyze(self):
        pdf_bytes = _build_sample_pdf_bytes("Rechnung Nr. 123 fuer Test GmbH")
        upload = FakeUploadFile("Rechnung.pdf", pdf_bytes)

        document = services.save_document(upload, self.db)
        self.assertIsNotNone(document.id)
        self.assertEqual(document.status, "uploaded")

        extraction = services.analyze_document_by_id(document.id, self.db)
        self.assertIn("Rechnung", extraction["text"])
        refreshed = self.db.query(Document).filter(Document.id == document.id).first()
        self.assertEqual(refreshed.status, "analyzed")
        self.assertGreater(refreshed.character_count, 0)

        dummy_provider = DummyAIProvider()
        with patch.object(services, "get_ai_provider", return_value=dummy_provider):
            result = services.analyze_document_ai_by_id(document.id, self.db)

        self.assertEqual(dummy_provider.calls, 1)
        self.assertIn("Rechnung", dummy_provider.received_text)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["document_type"], "letter")
        self.assertEqual(result["summary"], "Test summary")
        self.assertIsNone(result["error_message"])


if __name__ == "__main__":
    unittest.main()
