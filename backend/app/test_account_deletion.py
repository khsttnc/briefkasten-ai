"""Account self-deletion (GDPR Art. 17) tests, in two layers, mirroring
test_ownership.py's structure:

- AccountDeletionServiceTestCase: direct account_deletion.py calls against
  an isolated in-memory database and temp upload directory - covers the
  deletion order/atomicity guarantees (Stripe first, files all-or-nothing,
  then DB, then Supabase Auth last).
- AccountDeletionRouteTestCase: real HTTP requests through FastAPI's
  TestClient with real (test-secret-signed) JWTs - covers the server-side
  confirmation-email check on DELETE /account.

The real backend/briefkasten.db and backend/uploads/ are never touched.
"""
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from . import account_deletion, services
from .database import get_db
from .jwt_test_support import generate_keypair, make_token, patch_jwks
from .main import app
from .models import Base, Document, DocumentAIAnalysis, Subscription, User


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


class AccountDeletionServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="briefkasten_account_deletion_test_"))
        self.upload_root_patcher = patch.object(services, "UPLOAD_ROOT", self.tmp_dir.resolve())
        self.upload_root_patcher.start()

        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.db = self.SessionLocal()

        self.user = User(external_auth_id="user-a", email="a@example.com")
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

        self.supabase_patcher = patch.object(account_deletion, "delete_supabase_auth_user")
        self.mock_delete_supabase_user = self.supabase_patcher.start()

    def tearDown(self):
        self.supabase_patcher.stop()
        self.db.close()
        self.upload_root_patcher.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _upload_document(self, filename: str, text: str) -> Document:
        pdf_bytes = _build_sample_pdf_bytes(text)
        return services.save_document(FakeUploadFile(filename, pdf_bytes), self.db, owner_id=self.user.id)

    def test_preview_reports_document_count_and_no_active_subscription(self):
        self._upload_document("A.pdf", "doc a")
        self._upload_document("B.pdf", "doc b")

        preview = account_deletion.get_deletion_preview(self.user, self.db)

        self.assertEqual(preview["document_count"], 2)
        self.assertFalse(preview["has_active_subscription"])
        self.assertIsNone(preview["subscription_plan"])

    def test_preview_reports_active_subscription(self):
        subscription = Subscription(
            user_id=self.user.id,
            stripe_customer_id="cus_123",
            stripe_subscription_id="sub_123",
            plan="pro",
            status="active",
        )
        self.db.add(subscription)
        self.db.commit()

        preview = account_deletion.get_deletion_preview(self.user, self.db)

        self.assertTrue(preview["has_active_subscription"])
        self.assertEqual(preview["subscription_plan"], "pro")

    def test_delete_account_removes_files_db_rows_and_supabase_identity(self):
        document = self._upload_document("A.pdf", "doc a")
        file_path = Path(document.filepath)
        self.assertTrue(file_path.exists())
        document_id = document.id
        user_id = self.user.id
        external_auth_id = self.user.external_auth_id

        account_deletion.delete_account(self.user, self.db)

        self.assertFalse(file_path.exists())
        self.assertIsNone(self.db.query(User).filter(User.id == user_id).first())
        self.assertIsNone(self.db.query(Document).filter(Document.id == document_id).first())
        self.mock_delete_supabase_user.assert_called_once_with(external_auth_id)

    def test_delete_account_cascades_to_document_analyses(self):
        document = self._upload_document("A.pdf", "doc a")
        analysis = DocumentAIAnalysis(document_id=document.id, provider="dummy", model="dummy", status="completed")
        self.db.add(analysis)
        self.db.commit()
        analysis_id = analysis.id

        account_deletion.delete_account(self.user, self.db)

        self.assertIsNone(
            self.db.query(DocumentAIAnalysis).filter(DocumentAIAnalysis.id == analysis_id).first()
        )

    def test_delete_account_cancels_active_stripe_subscription_first(self):
        subscription = Subscription(
            user_id=self.user.id,
            stripe_customer_id="cus_123",
            stripe_subscription_id="sub_123",
            plan="pro",
            status="active",
        )
        self.db.add(subscription)
        self.db.commit()
        user_id = self.user.id

        with patch.object(account_deletion, "cancel_subscription_immediately") as mock_cancel:
            account_deletion.delete_account(self.user, self.db)

        mock_cancel.assert_called_once_with("sub_123")
        self.assertIsNone(self.db.query(User).filter(User.id == user_id).first())

    def test_delete_account_skips_stripe_when_already_canceled(self):
        subscription = Subscription(
            user_id=self.user.id,
            stripe_customer_id="cus_123",
            stripe_subscription_id="sub_123",
            plan="pro",
            status="canceled",
        )
        self.db.add(subscription)
        self.db.commit()

        with patch.object(account_deletion, "cancel_subscription_immediately") as mock_cancel:
            account_deletion.delete_account(self.user, self.db)

        mock_cancel.assert_not_called()

    def test_stripe_cancellation_failure_aborts_before_touching_files_or_db(self):
        document = self._upload_document("A.pdf", "doc a")
        file_path = Path(document.filepath)
        subscription = Subscription(
            user_id=self.user.id,
            stripe_customer_id="cus_123",
            stripe_subscription_id="sub_123",
            plan="pro",
            status="active",
        )
        self.db.add(subscription)
        self.db.commit()
        user_id = self.user.id

        with patch.object(
            account_deletion,
            "cancel_subscription_immediately",
            side_effect=HTTPException(status_code=502, detail="Stripe unavailable"),
        ):
            with self.assertRaises(HTTPException) as ctx:
                account_deletion.delete_account(self.user, self.db)

        self.assertEqual(ctx.exception.status_code, 502)
        self.assertTrue(file_path.exists())
        self.assertIsNotNone(self.db.query(User).filter(User.id == user_id).first())
        self.mock_delete_supabase_user.assert_not_called()

    def test_file_deletion_failure_aborts_before_any_db_row_is_deleted(self):
        document_kept = self._upload_document("keep.pdf", "kept")
        document_broken = self._upload_document("broken.pdf", "broken")
        user_id = self.user.id
        kept_id = document_kept.id
        broken_id = document_broken.id

        with patch("os.remove", side_effect=PermissionError("locked")):
            with self.assertRaises(HTTPException) as ctx:
                account_deletion.delete_account(self.user, self.db)

        self.assertEqual(ctx.exception.status_code, 500)
        # Account remains fully intact - never half-deleted.
        self.assertIsNotNone(self.db.query(User).filter(User.id == user_id).first())
        self.assertIsNotNone(self.db.query(Document).filter(Document.id == kept_id).first())
        self.assertIsNotNone(self.db.query(Document).filter(Document.id == broken_id).first())
        self.mock_delete_supabase_user.assert_not_called()

    def test_already_missing_file_is_not_an_error(self):
        document = self._upload_document("A.pdf", "doc a")
        Path(document.filepath).unlink()

        account_deletion.delete_account(self.user, self.db)

        self.assertIsNone(self.db.query(User).filter(User.id == self.user.id).first())

    def test_supabase_failure_still_leaves_local_data_deleted(self):
        # Deliberate ordering: Supabase Auth deletion runs LAST, so a
        # failure there must not roll back the already-committed local
        # deletion (see account_deletion.py's module docstring).
        document = self._upload_document("A.pdf", "doc a")
        user_id = self.user.id
        document_id = document.id
        self.mock_delete_supabase_user.side_effect = HTTPException(status_code=502, detail="boom")

        with self.assertRaises(HTTPException):
            account_deletion.delete_account(self.user, self.db)

        self.assertIsNone(self.db.query(User).filter(User.id == user_id).first())
        self.assertIsNone(self.db.query(Document).filter(Document.id == document_id).first())


class AccountDeletionRouteTestCase(unittest.TestCase):
    """Full-stack tests for the server-side confirmation-email check on
    DELETE /account, through real HTTP requests with real signed JWTs."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="briefkasten_account_deletion_route_test_"))
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

        self.supabase_patcher = patch.object(account_deletion, "delete_supabase_auth_user")
        self.supabase_patcher.start()

    def tearDown(self):
        self.supabase_patcher.stop()
        app.dependency_overrides.pop(get_db, None)
        self.upload_root_patcher.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_delete_account_with_mismatched_confirmation_email_is_400(self):
        token = make_token(sub="user-a", private_key=self.private_key, email="a@example.com")
        # Just-in-time-provision the user first (same as any other route).
        self.client.get("/documents", headers={"Authorization": f"Bearer {token}"})

        response = self.client.request(
            "DELETE",
            "/account",
            headers={"Authorization": f"Bearer {token}"},
            json={"confirmation_email": "wrong@example.com"},
        )

        self.assertEqual(response.status_code, 400)
        db = self.SessionLocal()
        try:
            self.assertIsNotNone(db.query(User).filter(User.external_auth_id == "user-a").first())
        finally:
            db.close()

    def test_delete_account_with_matching_confirmation_email_succeeds(self):
        token = make_token(sub="user-a", private_key=self.private_key, email="a@example.com")
        self.client.get("/documents", headers={"Authorization": f"Bearer {token}"})

        response = self.client.request(
            "DELETE",
            "/account",
            headers={"Authorization": f"Bearer {token}"},
            json={"confirmation_email": "A@Example.com"},
        )

        self.assertEqual(response.status_code, 200)
        db = self.SessionLocal()
        try:
            self.assertIsNone(db.query(User).filter(User.external_auth_id == "user-a").first())
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
