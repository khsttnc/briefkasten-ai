"""Ownership enforcement tests, in two layers:

- OwnershipServiceLayerTestCase: direct services.py calls (fast, mirrors the
  existing test_pipeline_integration.py style) - proves the owner_id filter
  itself is correct, including cross-user denial and legacy documents.
- AuthRouteTestCase: real HTTP requests through FastAPI's TestClient with
  real (test-secret-signed) JWTs - proves the full stack wires together:
  Authorization header -> get_current_user -> JWT verification -> service
  ownership filter.

Both use an isolated in-memory database and temp upload directory. The real
backend/briefkasten.db and backend/uploads/ are never touched.
"""
import io
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import fitz
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from . import services
from .database import get_db
from .jwt_test_support import generate_keypair, make_token, patch_jwks
from .main import app
from .models import Base, Document, User


class FakeUploadFile:
    def __init__(self, filename: str, content: bytes):
        self.filename = filename
        self.file = io.BytesIO(content)


def _build_sample_pdf_bytes(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


class OwnershipServiceLayerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="briefkasten_ownership_test_"))
        self.upload_root_patcher = patch.object(services, "UPLOAD_ROOT", self.tmp_dir.resolve())
        self.upload_root_patcher.start()

        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.db = self.SessionLocal()

        self.user_a = User(external_auth_id="user-a", email="a@example.com")
        self.user_b = User(external_auth_id="user-b", email="b@example.com")
        self.db.add_all([self.user_a, self.user_b])
        self.db.commit()
        self.db.refresh(self.user_a)
        self.db.refresh(self.user_b)

    def tearDown(self):
        self.db.close()
        self.upload_root_patcher.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_owner_can_access_own_document(self):
        pdf_bytes = _build_sample_pdf_bytes("Rechnung fuer User A")
        document = services.save_document(
            FakeUploadFile("A.pdf", pdf_bytes), self.db, owner_id=self.user_a.id
        )
        result = services.analyze_document_by_id(document.id, self.db, owner_id=self.user_a.id)
        self.assertIn("Rechnung", result["text"])

    def test_other_user_gets_404_not_403_on_text_extraction(self):
        pdf_bytes = _build_sample_pdf_bytes("Private document of User A")
        document = services.save_document(
            FakeUploadFile("A.pdf", pdf_bytes), self.db, owner_id=self.user_a.id
        )
        with self.assertRaises(HTTPException) as ctx:
            services.analyze_document_by_id(document.id, self.db, owner_id=self.user_b.id)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_other_user_gets_404_on_ai_analysis_even_when_cached(self):
        pdf_bytes = _build_sample_pdf_bytes("Private document of User A")
        document = services.save_document(
            FakeUploadFile("A.pdf", pdf_bytes), self.db, owner_id=self.user_a.id
        )
        services.analyze_document_by_id(document.id, self.db, owner_id=self.user_a.id)

        class DummyProvider:
            provider_name = "dummy"
            model_name = "dummy-model"

            def analyze_document(self, text):
                from .ai_service import AIAnalysisResult

                return AIAnalysisResult(document_type="letter", summary="s")

        with patch.object(services, "get_ai_provider", return_value=DummyProvider()):
            # User A populates the cache.
            services.analyze_document_ai_by_id(document.id, self.db, owner_id=self.user_a.id)
            # User B must never see it, cached or not.
            with self.assertRaises(HTTPException) as ctx:
                services.analyze_document_ai_by_id(document.id, self.db, owner_id=self.user_b.id)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_nonexistent_document_id_gets_404(self):
        with self.assertRaises(HTTPException) as ctx:
            services.analyze_document_by_id(999999, self.db, owner_id=self.user_a.id)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_deprecated_filename_route_is_owner_scoped(self):
        # Both users upload a file with the identical display name - each
        # must only ever be able to reach their own.
        pdf_a = _build_sample_pdf_bytes("User A content")
        pdf_b = _build_sample_pdf_bytes("User B content")
        services.save_document(FakeUploadFile("Bescheid.pdf", pdf_a), self.db, owner_id=self.user_a.id)
        services.save_document(FakeUploadFile("Bescheid.pdf", pdf_b), self.db, owner_id=self.user_b.id)

        result_a = services.analyze_document(
            "Bescheid.pdf", self.db, owner_id=self.user_a.id
        )
        result_b = services.analyze_document(
            "Bescheid.pdf", self.db, owner_id=self.user_b.id
        )
        self.assertIn("User A", result_a["text"])
        self.assertIn("User B", result_b["text"])

    def test_legacy_style_document_behaves_like_any_owned_document(self):
        # Simulates a backfilled pre-auth document: just a normal owner_id,
        # no special-casing anywhere in the ownership filter.
        legacy_user = User(external_auth_id="legacy-import", email=None)
        self.db.add(legacy_user)
        self.db.commit()
        self.db.refresh(legacy_user)

        pdf_bytes = _build_sample_pdf_bytes("Legacy document")
        document = Document(
            filename="Legacy.pdf", filepath=str(self.tmp_dir / "legacy.pdf"),
            status="uploaded", owner_id=legacy_user.id,
        )
        (self.tmp_dir / "legacy.pdf").write_bytes(pdf_bytes)
        self.db.add(document)
        self.db.commit()
        self.db.refresh(document)

        result = services.analyze_document_by_id(document.id, self.db, owner_id=legacy_user.id)
        self.assertIn("Legacy", result["text"])

        with self.assertRaises(HTTPException) as ctx:
            services.analyze_document_by_id(document.id, self.db, owner_id=self.user_a.id)
        self.assertEqual(ctx.exception.status_code, 404)


class AuthRouteTestCase(unittest.TestCase):
    """Full-stack tests through real HTTP requests: Authorization header ->
    get_current_user -> JWT verification -> service ownership filter."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="briefkasten_route_test_"))
        self.upload_root_patcher = patch.object(services, "UPLOAD_ROOT", self.tmp_dir.resolve())
        self.upload_root_patcher.start()

        # StaticPool: FastAPI runs sync route/dependency code in a thread
        # pool, and a plain sqlite://:memory: engine hands each new
        # connection its own separate, empty in-memory database per
        # thread - StaticPool forces one shared connection for the whole
        # engine so every request sees the same tables/data.
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.private_key, self.jwks = generate_keypair()
        patch_jwks(self, self.jwks)
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        self.upload_root_patcher.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _upload(self, token: str, filename: str, text: str):
        pdf_bytes = _build_sample_pdf_bytes(text)
        return self.client.post(
            "/upload",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (filename, pdf_bytes, "application/pdf")},
        )

    def test_upload_without_authorization_header_is_401(self):
        pdf_bytes = _build_sample_pdf_bytes("no auth")
        response = self.client.post("/upload", files={"file": ("A.pdf", pdf_bytes, "application/pdf")})
        self.assertEqual(response.status_code, 401)

    def test_upload_with_malformed_token_is_401(self):
        response = self._upload("not-a-real-jwt", "A.pdf", "bad token")
        self.assertEqual(response.status_code, 401)

    def test_upload_with_wrong_signature_is_401(self):
        wrong_private_key, _ = generate_keypair()
        bad_token = make_token(sub="user-a", private_key=wrong_private_key)
        response = self._upload(bad_token, "A.pdf", "wrong sig")
        self.assertEqual(response.status_code, 401)

    def test_upload_with_expired_token_is_401(self):
        expired_token = make_token(sub="user-a", private_key=self.private_key, expires_delta=timedelta(hours=-1))
        response = self._upload(expired_token, "A.pdf", "expired")
        self.assertEqual(response.status_code, 401)

    def test_valid_token_full_upload_and_analyze_flow_succeeds(self):
        token = make_token(sub="user-a", private_key=self.private_key)
        upload_response = self._upload(token, "A.pdf", "Rechnung Nr. 42")
        self.assertEqual(upload_response.status_code, 200)
        document_id = upload_response.json()["id"]

        analyze_response = self.client.get(
            f"/analyze/id/{document_id}", headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(analyze_response.status_code, 200)
        self.assertIn("Rechnung", analyze_response.json()["text"])

    def test_cross_user_document_access_is_404(self):
        token_a = make_token(sub="user-a", private_key=self.private_key)
        token_b = make_token(sub="user-b", private_key=self.private_key)

        upload_response = self._upload(token_a, "A.pdf", "User A's private letter")
        document_id = upload_response.json()["id"]

        response = self.client.get(
            f"/analyze/id/{document_id}", headers={"Authorization": f"Bearer {token_b}"}
        )
        self.assertEqual(response.status_code, 404)

    def test_first_request_for_a_new_sub_provisions_a_user_row(self):
        token = make_token(sub="brand-new-user", private_key=self.private_key)
        response = self._upload(token, "New.pdf", "first ever request")
        self.assertEqual(response.status_code, 200)

        db = self.SessionLocal()
        try:
            user = db.query(User).filter(User.external_auth_id == "brand-new-user").first()
            self.assertIsNotNone(user)
            self.assertEqual(user.email, "brand-new-user@example.com")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
