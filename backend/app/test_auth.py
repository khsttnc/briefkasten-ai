import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .auth import JWT_ALGORITHM, JWT_AUDIENCE, get_current_user
from .models import Base, User

TEST_SECRET = "test-supabase-jwt-secret"


def _make_token(secret: str = TEST_SECRET, sub: str = "auth0|abc123", email: str = "user@example.com",
                 expires_delta: timedelta = timedelta(hours=1), audience: str = JWT_AUDIENCE) -> str:
    payload = {
        "sub": sub,
        "email": email,
        "aud": audience,
        "exp": datetime.now(timezone.utc) + expires_delta,
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


class GetCurrentUserTestCase(unittest.TestCase):
    """Isolated unit tests for the Supabase JWT verification dependency -
    an in-memory database, no HTTP layer, no real Supabase project involved."""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.db = self.SessionLocal()
        self.env_patcher = patch.dict("os.environ", {"SUPABASE_JWT_SECRET": TEST_SECRET})
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        self.db.close()

    def test_missing_authorization_header_raises_401(self):
        with self.assertRaises(HTTPException) as ctx:
            get_current_user(authorization=None, db=self.db)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_header_without_bearer_prefix_raises_401(self):
        with self.assertRaises(HTTPException) as ctx:
            get_current_user(authorization="Token abc123", db=self.db)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_missing_secret_configuration_raises_503(self):
        self.env_patcher.stop()
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(HTTPException) as ctx:
                get_current_user(authorization=f"Bearer {_make_token()}", db=self.db)
            self.assertEqual(ctx.exception.status_code, 503)
        self.env_patcher.start()

    def test_invalid_signature_raises_401(self):
        token = _make_token(secret="wrong-secret")
        with self.assertRaises(HTTPException) as ctx:
            get_current_user(authorization=f"Bearer {token}", db=self.db)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_expired_token_raises_401(self):
        token = _make_token(expires_delta=timedelta(hours=-1))
        with self.assertRaises(HTTPException) as ctx:
            get_current_user(authorization=f"Bearer {token}", db=self.db)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_wrong_audience_raises_401(self):
        token = _make_token(audience="not-authenticated")
        with self.assertRaises(HTTPException) as ctx:
            get_current_user(authorization=f"Bearer {token}", db=self.db)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_missing_sub_claim_raises_401(self):
        token = jwt.encode(
            {"email": "user@example.com", "aud": JWT_AUDIENCE,
             "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
            TEST_SECRET, algorithm=JWT_ALGORITHM,
        )
        with self.assertRaises(HTTPException) as ctx:
            get_current_user(authorization=f"Bearer {token}", db=self.db)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_valid_token_new_user_is_provisioned_just_in_time(self):
        token = _make_token(sub="supabase-uid-1", email="new@example.com")
        user = get_current_user(authorization=f"Bearer {token}", db=self.db)

        self.assertIsNotNone(user.id)
        self.assertEqual(user.external_auth_id, "supabase-uid-1")
        self.assertEqual(user.email, "new@example.com")

        all_users = self.db.query(User).all()
        self.assertEqual(len(all_users), 1)

    def test_valid_token_existing_user_is_reused_not_duplicated(self):
        token = _make_token(sub="supabase-uid-2", email="existing@example.com")
        first = get_current_user(authorization=f"Bearer {token}", db=self.db)
        second = get_current_user(authorization=f"Bearer {token}", db=self.db)

        self.assertEqual(first.id, second.id)
        all_users = self.db.query(User).filter(User.external_auth_id == "supabase-uid-2").all()
        self.assertEqual(len(all_users), 1)


if __name__ == "__main__":
    unittest.main()
