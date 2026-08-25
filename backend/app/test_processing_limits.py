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
from .models import Base, Document, User
from .test_pipeline_integration import FakeUploadFile


def _create_test_user(db, external_auth_id: str = "test-user") -> User:
    user = User(external_auth_id=external_auth_id, email=f"{external_auth_id}@example.com")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _pdf_with_page_count(n: int) -> bytes:
    doc = fitz.open()
    for _ in range(n):
        doc.new_page()
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def _pdf_with_page_size(width: float, height: float) -> bytes:
    doc = fitz.open()
    doc.new_page(width=width, height=height)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


class DocumentPageLimitsTestCase(unittest.TestCase):
    """Regression coverage for the security-review finding that a small
    file on disk could still declare an unbounded page count or an
    enormous page size, turning text/OCR extraction into an unbounded
    CPU/memory sink. Uses an isolated temp upload dir and in-memory DB -
    the real backend/briefkasten.db and backend/uploads/ are never
    touched. MAX_DOCUMENT_PAGES/MAX_PAGE_DIMENSION_POINTS are patched to
    small values so the fixtures stay tiny and fast regardless of the
    real production defaults."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="briefkasten_page_limit_test_"))
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

    def _upload(self, pdf_bytes: bytes, filename: str = "test.pdf") -> Document:
        upload = FakeUploadFile(filename, pdf_bytes)
        return services.save_document(upload, self.db, owner_id=self.owner_id)

    def test_document_within_page_limit_is_analyzed_normally(self):
        with patch.object(services, "MAX_DOCUMENT_PAGES", 5):
            document = self._upload(_pdf_with_page_count(3))
            result = services.analyze_document_by_id(document.id, self.db, owner_id=self.owner_id)

        self.assertEqual(result["characters"], 0)  # blank pages, but no error
        refreshed = self.db.query(Document).filter(Document.id == document.id).first()
        self.assertIn(refreshed.status, ("analyzed", "ocr_required"))

    def test_document_over_page_limit_is_rejected(self):
        with patch.object(services, "MAX_DOCUMENT_PAGES", 5):
            document = self._upload(_pdf_with_page_count(6))
            with self.assertRaises(HTTPException) as ctx:
                services.analyze_document_by_id(document.id, self.db, owner_id=self.owner_id)

        self.assertEqual(ctx.exception.status_code, 413)
        self.assertIn("pages", ctx.exception.detail)

    def test_document_over_page_limit_is_not_persisted_as_analyzed(self):
        # A rejected document must not be silently marked analyzed/blank -
        # the caller should be able to see the analysis never happened.
        with patch.object(services, "MAX_DOCUMENT_PAGES", 5):
            document = self._upload(_pdf_with_page_count(6))
            with self.assertRaises(HTTPException):
                services.analyze_document_by_id(document.id, self.db, owner_id=self.owner_id)

        refreshed = self.db.query(Document).filter(Document.id == document.id).first()
        self.assertEqual(refreshed.status, "uploaded")
        self.assertIsNone(refreshed.character_count)

    def test_page_within_dimension_limit_is_analyzed_normally(self):
        with patch.object(services, "MAX_PAGE_DIMENSION_POINTS", 1000):
            document = self._upload(_pdf_with_page_size(600, 800))
            result = services.analyze_document_by_id(document.id, self.db, owner_id=self.owner_id)

        self.assertEqual(result["characters"], 0)

    def test_oversized_page_is_rejected(self):
        with patch.object(services, "MAX_PAGE_DIMENSION_POINTS", 1000):
            document = self._upload(_pdf_with_page_size(2000, 800))
            with self.assertRaises(HTTPException) as ctx:
                services.analyze_document_by_id(document.id, self.db, owner_id=self.owner_id)

        self.assertEqual(ctx.exception.status_code, 413)
        self.assertIn("too large", ctx.exception.detail)

    def test_extract_text_with_ocr_rejects_oversized_page_directly(self):
        # A page with no extractable text falls through to OCR
        # (extract_text_with_ocr), which independently re-opens the file
        # and must apply the same limit rather than proceeding straight to
        # get_pixmap() on an oversized page.
        with patch.object(services, "MAX_PAGE_DIMENSION_POINTS", 1000):
            document = self._upload(_pdf_with_page_size(2000, 800), filename="scan.pdf")
            with self.assertRaises(HTTPException) as ctx:
                services.extract_text_with_ocr(document.filepath)

        self.assertEqual(ctx.exception.status_code, 413)


if __name__ == "__main__":
    unittest.main()
