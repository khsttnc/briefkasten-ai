import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import fitz
from fastapi import HTTPException

from . import services


class FakeUploadFile:
    """Minimal stand-in for fastapi.UploadFile exposing what save_document uses."""

    def __init__(self, filename: str, content: bytes):
        self.filename = filename
        self.file = io.BytesIO(content)


def _valid_pdf_bytes() -> bytes:
    """A genuinely valid, minimal one-page PDF, for tests that need to get
    past content validation to exercise unrelated behavior (path traversal,
    filename sanitization, etc.)."""
    doc = fitz.open()
    doc.new_page()
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


class UploadSecurityTestCase(unittest.TestCase):
    """Verifies save_document() never writes outside a temp upload root and
    never uses a client-supplied filename as a filesystem path. Uses an
    isolated temp directory and a mocked DB session, so the real
    backend/briefkasten.db and backend/uploads/ are never touched."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="briefkasten_upload_test_"))
        self.upload_root_patcher = patch.object(services, "UPLOAD_ROOT", self.tmp_dir.resolve())
        self.upload_root_patcher.start()
        self.db = MagicMock()

    def tearDown(self):
        self.upload_root_patcher.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _tmp_dir_contents(self):
        return list(self.tmp_dir.iterdir())

    def test_normal_filename_is_saved_inside_upload_root(self):
        upload = FakeUploadFile("invoice.pdf", _valid_pdf_bytes())

        document = services.save_document(upload, self.db)

        saved_path = Path(document.filepath).resolve()
        self.assertEqual(saved_path.parent, self.tmp_dir.resolve())
        self.assertTrue(saved_path.exists())
        self.assertEqual(document.filename, "invoice.pdf")
        # Storage name must not be the raw client filename.
        self.assertNotEqual(saved_path.name, "invoice.pdf")
        self.assertEqual(saved_path.suffix, ".pdf")

    def test_path_traversal_filename_cannot_escape_upload_root(self):
        upload = FakeUploadFile("../../../../etc/passwd.pdf", _valid_pdf_bytes())

        document = services.save_document(upload, self.db)

        saved_path = Path(document.filepath).resolve()
        self.assertEqual(saved_path.parent, self.tmp_dir.resolve())
        self.assertTrue(str(saved_path).startswith(str(self.tmp_dir.resolve())))
        # Display metadata must not retain traversal path segments.
        self.assertNotIn("..", document.filename)
        self.assertNotIn("/", document.filename)
        self.assertNotIn("\\", document.filename)

    def test_absolute_path_filename_cannot_escape_upload_root(self):
        upload = FakeUploadFile("/etc/passwd.pdf", _valid_pdf_bytes())

        document = services.save_document(upload, self.db)

        saved_path = Path(document.filepath).resolve()
        self.assertEqual(saved_path.parent, self.tmp_dir.resolve())
        self.assertEqual(document.filename, "passwd.pdf")

    def test_windows_style_absolute_path_filename_is_contained(self):
        upload = FakeUploadFile("C:\\Windows\\System32\\evil.pdf", _valid_pdf_bytes())

        document = services.save_document(upload, self.db)

        saved_path = Path(document.filepath).resolve()
        self.assertEqual(saved_path.parent, self.tmp_dir.resolve())

    def test_unusual_characters_are_sanitized(self):
        upload = FakeUploadFile('w\x00eird<>:"|?*na\x01me.pdf', _valid_pdf_bytes())

        document = services.save_document(upload, self.db)

        saved_path = Path(document.filepath).resolve()
        self.assertEqual(saved_path.parent, self.tmp_dir.resolve())
        for forbidden in ["\x00", "\x01", "<", ">", ":", '"', "|", "?", "*"]:
            self.assertNotIn(forbidden, document.filename)

    def test_disallowed_extension_is_rejected(self):
        upload = FakeUploadFile("script.exe", b"MZ fake binary")

        with self.assertRaises(HTTPException) as ctx:
            services.save_document(upload, self.db)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(self._tmp_dir_contents(), [])

    def test_empty_file_is_rejected(self):
        upload = FakeUploadFile("empty.pdf", b"")

        with self.assertRaises(HTTPException) as ctx:
            services.save_document(upload, self.db)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(self._tmp_dir_contents(), [])

    def test_oversized_file_is_rejected_and_cleaned_up(self):
        upload = FakeUploadFile("big.pdf", b"x" * 100)

        with patch.object(services, "MAX_UPLOAD_SIZE_BYTES", 10):
            with self.assertRaises(HTTPException) as ctx:
                services.save_document(upload, self.db)

        self.assertEqual(ctx.exception.status_code, 413)
        # Partially-written file must be cleaned up, not left behind.
        self.assertEqual(self._tmp_dir_contents(), [])

    def test_valid_pdf_is_accepted(self):
        upload = FakeUploadFile("valid.pdf", _valid_pdf_bytes())

        document = services.save_document(upload, self.db)

        saved_path = Path(document.filepath).resolve()
        self.assertTrue(saved_path.exists())
        self.assertEqual(saved_path.parent, self.tmp_dir.resolve())

    def test_fake_pdf_content_is_rejected(self):
        upload = FakeUploadFile("fake.pdf", b"this is not a pdf, just plain text bytes")

        with self.assertRaises(HTTPException) as ctx:
            services.save_document(upload, self.db)

        self.assertEqual(ctx.exception.status_code, 400)
        # Rejected file must not be left behind on disk.
        self.assertEqual(self._tmp_dir_contents(), [])

    def test_corrupt_pdf_is_rejected(self):
        truncated = _valid_pdf_bytes()[:20]  # valid PDF header, but truncated/corrupt body
        upload = FakeUploadFile("corrupt.pdf", truncated)

        with self.assertRaises(HTTPException) as ctx:
            services.save_document(upload, self.db)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(self._tmp_dir_contents(), [])


if __name__ == "__main__":
    unittest.main()
