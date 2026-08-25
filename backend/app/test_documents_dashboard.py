"""Tests for the Step 5 dashboard: services.list_documents /
services.get_documents_summary, plus a full-stack check of the /documents
and /documents/summary routes through FastAPI's TestClient (mirrors
test_ownership.py's two-layer pattern). Uses an isolated in-memory database
and temp upload directory throughout - the real backend/briefkasten.db and
backend/uploads/ are never touched.
"""
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

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


def _make_document(db, owner_id: int, **overrides) -> Document:
    defaults = dict(
        filename="doc.pdf",
        filepath="/tmp/doc.pdf",
        status="analyzed",
        owner_id=owner_id,
    )
    defaults.update(overrides)
    document = Document(**defaults)
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


class ListDocumentsServiceTestCase(unittest.TestCase):
    def setUp(self):
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

    def test_only_returns_the_requesting_owners_documents(self):
        _make_document(self.db, self.user_a.id, filename="a.pdf")
        _make_document(self.db, self.user_b.id, filename="b.pdf")

        result = services.list_documents(self.db, owner_id=self.user_a.id)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["filename"], "a.pdf")

    def test_sorted_by_priority_severity_descending(self):
        _make_document(self.db, self.user_a.id, filename="low.pdf", priority_level="low")
        _make_document(self.db, self.user_a.id, filename="critical.pdf", priority_level="critical")
        _make_document(self.db, self.user_a.id, filename="normal.pdf", priority_level="normal")
        _make_document(self.db, self.user_a.id, filename="high.pdf", priority_level="high")

        result = services.list_documents(self.db, owner_id=self.user_a.id)

        self.assertEqual(
            [doc["filename"] for doc in result],
            ["critical.pdf", "high.pdf", "normal.pdf", "low.pdf"],
        )

    def test_unclassified_documents_sort_last(self):
        # priority_level is None until AI analysis + post-processing runs -
        # must not be treated as more urgent than "low".
        _make_document(self.db, self.user_a.id, filename="unclassified.pdf", priority_level=None)
        _make_document(self.db, self.user_a.id, filename="low.pdf", priority_level="low")

        result = services.list_documents(self.db, owner_id=self.user_a.id)

        self.assertEqual([doc["filename"] for doc in result], ["low.pdf", "unclassified.pdf"])

    def test_same_level_sorted_by_soonest_deadline_first(self):
        far = datetime(2026, 6, 1)
        soon = datetime(2026, 1, 15)
        no_deadline = None
        _make_document(
            self.db, self.user_a.id, filename="far.pdf", priority_level="high",
            deadline_estimated_date=far,
        )
        _make_document(
            self.db, self.user_a.id, filename="soon.pdf", priority_level="high",
            deadline_estimated_date=soon,
        )
        _make_document(
            self.db, self.user_a.id, filename="no_deadline.pdf", priority_level="high",
            deadline_estimated_date=no_deadline,
        )

        result = services.list_documents(self.db, owner_id=self.user_a.id)

        self.assertEqual(
            [doc["filename"] for doc in result],
            ["soon.pdf", "far.pdf", "no_deadline.pdf"],
        )

    def test_filters_by_priority_query_param(self):
        _make_document(self.db, self.user_a.id, filename="critical.pdf", priority_level="critical")
        _make_document(self.db, self.user_a.id, filename="low.pdf", priority_level="low")

        result = services.list_documents(self.db, owner_id=self.user_a.id, priority="critical")

        self.assertEqual([doc["filename"] for doc in result], ["critical.pdf"])

    def test_invalid_priority_value_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            services.list_documents(self.db, owner_id=self.user_a.id, priority="urgent")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_serialized_fields_include_document_intelligence_columns(self):
        _make_document(
            self.db, self.user_a.id,
            sender_category="Behörde",
            sender_institution="Jobcenter Berlin Mitte",
            document_type="Änderungsbescheid",
            priority_level="high",
            priority_reasoning="reasoning text",
            deadline_type="relative",
            deadline_estimated_date=datetime(2026, 1, 28),
            deadline_certainty="estimated",
            requires_action=True,
            action_summary="do something",
        )

        result = services.list_documents(self.db, owner_id=self.user_a.id)

        self.assertEqual(result[0]["sender_category"], "Behörde")
        self.assertEqual(result[0]["sender_institution"], "Jobcenter Berlin Mitte")
        self.assertEqual(result[0]["document_type"], "Änderungsbescheid")
        self.assertEqual(result[0]["priority_reasoning"], "reasoning text")
        self.assertEqual(result[0]["deadline_estimated_date"], "2026-01-28T00:00:00")
        self.assertTrue(result[0]["requires_action"])
        self.assertEqual(result[0]["action_summary"], "do something")


class DocumentsSummaryServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.db = self.SessionLocal()
        self.owner = User(external_auth_id="user-a", email="a@example.com")
        self.db.add(self.owner)
        self.db.commit()
        self.db.refresh(self.owner)

    def tearDown(self):
        self.db.close()

    def test_counts_by_level_plus_unclassified_and_total(self):
        _make_document(self.db, self.owner.id, priority_level="critical")
        _make_document(self.db, self.owner.id, priority_level="critical")
        _make_document(self.db, self.owner.id, priority_level="high")
        _make_document(self.db, self.owner.id, priority_level="normal")
        _make_document(self.db, self.owner.id, priority_level="low")
        _make_document(self.db, self.owner.id, priority_level=None)

        summary = services.get_documents_summary(self.db, owner_id=self.owner.id)

        self.assertEqual(summary["critical"], 2)
        self.assertEqual(summary["high"], 1)
        self.assertEqual(summary["normal"], 1)
        self.assertEqual(summary["low"], 1)
        self.assertEqual(summary["unclassified"], 1)
        self.assertEqual(summary["total"], 6)

    def test_no_documents_yields_all_zero_counts(self):
        summary = services.get_documents_summary(self.db, owner_id=self.owner.id)
        self.assertEqual(summary, {
            "critical": 0, "high": 0, "normal": 0, "low": 0,
            "unclassified": 0, "total": 0,
        })

    def test_only_counts_the_requesting_owners_documents(self):
        other_owner = User(external_auth_id="user-b", email="b@example.com")
        self.db.add(other_owner)
        self.db.commit()
        self.db.refresh(other_owner)

        _make_document(self.db, self.owner.id, priority_level="critical")
        _make_document(self.db, other_owner.id, priority_level="critical")
        _make_document(self.db, other_owner.id, priority_level="critical")

        summary = services.get_documents_summary(self.db, owner_id=self.owner.id)
        self.assertEqual(summary["critical"], 1)
        self.assertEqual(summary["total"], 1)


class DocumentsRouteTestCase(unittest.TestCase):
    """Full-stack: real HTTP requests through FastAPI's TestClient with a
    real (test-secret-signed) JWT, same pattern as
    test_ownership.py::AuthRouteTestCase."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="briefkasten_documents_route_test_"))
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

        db = self.SessionLocal()
        self.owner = User(external_auth_id="user-a", email="a@example.com")
        db.add(self.owner)
        db.commit()
        db.refresh(self.owner)
        _make_document(db, self.owner.id, filename="critical.pdf", priority_level="critical")
        _make_document(db, self.owner.id, filename="low.pdf", priority_level="low")
        db.close()

        self.token = make_token(sub="user-a", private_key=self.private_key)

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        self.upload_root_patcher.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_documents_route_without_auth_is_401(self):
        response = self.client.get("/documents")
        self.assertEqual(response.status_code, 401)

    def test_documents_summary_route_without_auth_is_401(self):
        response = self.client.get("/documents/summary")
        self.assertEqual(response.status_code, 401)

    def test_documents_route_returns_owners_documents(self):
        response = self.client.get("/documents", headers={"Authorization": f"Bearer {self.token}"})
        self.assertEqual(response.status_code, 200)
        filenames = [doc["filename"] for doc in response.json()]
        self.assertEqual(filenames, ["critical.pdf", "low.pdf"])

    def test_documents_route_priority_filter(self):
        response = self.client.get(
            "/documents", params={"priority": "critical"},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(response.status_code, 200)
        filenames = [doc["filename"] for doc in response.json()]
        self.assertEqual(filenames, ["critical.pdf"])

    def test_documents_route_invalid_priority_is_400(self):
        response = self.client.get(
            "/documents", params={"priority": "not-a-level"},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(response.status_code, 400)

    def test_documents_summary_route_returns_counts(self):
        response = self.client.get(
            "/documents/summary", headers={"Authorization": f"Bearer {self.token}"}
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["critical"], 1)
        self.assertEqual(body["low"], 1)
        self.assertEqual(body["total"], 2)


if __name__ == "__main__":
    unittest.main()
