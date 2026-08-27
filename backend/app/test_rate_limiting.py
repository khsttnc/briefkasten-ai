"""Regression coverage for the security-review finding that /upload and
the AI-analyze endpoint had no request-rate limit at all - a single
account could call either unboundedly (CPU-exhaustion DoS via OCR, and
cost-abuse against the paid AI provider API). Full-stack: real HTTP
requests through FastAPI's TestClient with a real (test-secret-signed)
JWT, same pattern as test_documents_dashboard.py::DocumentsRouteTestCase.
"""
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from . import services
from .ai_service import AIAnalysisResult
from .config import AI_ANALYZE_RATE_LIMIT, UPLOAD_RATE_LIMIT
from .database import get_db
from .jwt_test_support import generate_keypair, make_token, patch_jwks
from .main import app, limiter
from .models import Base, Document, User


def _rate_limit_count(limit_str: str) -> int:
    # slowapi rate strings look like "10/minute" - extract the leading count
    # so these tests stay correct if the configured numbers are retuned.
    match = re.match(r"(\d+)/", limit_str)
    assert match, f"unexpected rate limit format: {limit_str!r}"
    return int(match.group(1))


def _valid_pdf_bytes() -> bytes:
    doc = fitz.open()
    doc.new_page()
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


class DummyAIProvider:
    provider_name = "dummy"
    model_name = "dummy-model"

    def analyze_document(self, text: str, **kwargs) -> AIAnalysisResult:
        return AIAnalysisResult(
            document_type="letter",
            language="de",
            summary="Test summary",
            turkish_explanation="Test aciklama",
            important_dates=[],
            extracted_entities=[],
            raw_response={"document_type": "letter"},
        )


class RateLimitingTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="briefkasten_rate_limit_test_"))
        self.upload_root_patcher = patch.object(services, "UPLOAD_ROOT", self.tmp_dir.resolve())
        self.upload_root_patcher.start()

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

        # A fresh in-memory limiter storage per test - the real one is a
        # module-level singleton shared across the whole test process, so
        # without this, an earlier test's requests would still count
        # against this one.
        limiter.reset()

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        self.upload_root_patcher.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _token_for(self, sub: str) -> str:
        return make_token(sub=sub, private_key=self.private_key)

    def test_upload_route_is_blocked_after_exceeding_the_limit(self):
        token = self._token_for("upload-limit-user")
        headers = {"Authorization": f"Bearer {token}"}
        limit = _rate_limit_count(UPLOAD_RATE_LIMIT)

        statuses = []
        for _ in range(limit + 1):
            pdf_bytes = _valid_pdf_bytes()
            response = self.client.post(
                "/upload",
                headers=headers,
                files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
            )
            statuses.append(response.status_code)

        self.assertEqual(statuses[:limit], [200] * limit)
        self.assertEqual(statuses[limit], 429)

    def test_upload_rate_limit_is_scoped_per_user_not_shared(self):
        limit = _rate_limit_count(UPLOAD_RATE_LIMIT)
        token_a = self._token_for("upload-user-a")
        token_b = self._token_for("upload-user-b")

        # Exhaust user A's budget entirely.
        for _ in range(limit):
            response = self.client.post(
                "/upload",
                headers={"Authorization": f"Bearer {token_a}"},
                files={"file": ("test.pdf", _valid_pdf_bytes(), "application/pdf")},
            )
            self.assertEqual(response.status_code, 200)
        blocked = self.client.post(
            "/upload",
            headers={"Authorization": f"Bearer {token_a}"},
            files={"file": ("test.pdf", _valid_pdf_bytes(), "application/pdf")},
        )
        self.assertEqual(blocked.status_code, 429)

        # User B must be unaffected by user A's usage.
        response = self.client.post(
            "/upload",
            headers={"Authorization": f"Bearer {token_b}"},
            files={"file": ("test.pdf", _valid_pdf_bytes(), "application/pdf")},
        )
        self.assertEqual(response.status_code, 200)

    def test_ai_analyze_route_is_blocked_after_exceeding_the_limit(self):
        db = self.SessionLocal()
        owner = User(external_auth_id="analyze-limit-user", email="a@example.com")
        db.add(owner)
        db.commit()
        db.refresh(owner)
        document = Document(
            filename="doc.pdf",
            filepath=str(self.tmp_dir / "doc.pdf"),
            status="analyzed",
            text="Sehr geehrte Damen und Herren",
            character_count=30,
            owner_id=owner.id,
        )
        db.add(document)
        db.commit()
        db.refresh(document)
        document_id = document.id
        db.close()

        token = self._token_for("analyze-limit-user")
        headers = {"Authorization": f"Bearer {token}"}
        limit = _rate_limit_count(AI_ANALYZE_RATE_LIMIT)

        statuses = []
        with patch.object(services, "get_ai_provider", return_value=DummyAIProvider()):
            for _ in range(limit + 1):
                response = self.client.post(
                    f"/analyze/id/{document_id}/ai",
                    headers=headers,
                    params={"force": "true"},
                )
                statuses.append(response.status_code)

        self.assertEqual(statuses[:limit], [200] * limit)
        self.assertEqual(statuses[limit], 429)


if __name__ == "__main__":
    unittest.main()
