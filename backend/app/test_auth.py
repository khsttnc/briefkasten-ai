import unittest
from datetime import timedelta
from unittest.mock import patch

from fastapi import HTTPException
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from . import auth as auth_module
from .auth import get_current_user
from .jwt_test_support import TEST_SUPABASE_URL, generate_keypair, make_token, patch_jwks
from .models import Base, User


class GetCurrentUserTestCase(unittest.TestCase):
    """Isolated unit tests for the Supabase JWT verification dependency -
    an in-memory database, no HTTP layer, no real Supabase project involved.
    A throwaway EC keypair stands in for Supabase's ES256 project signing
    key, and PyJWKClient.fetch_data is mocked so no real JWKS network call
    ever happens (see jwt_test_support.patch_jwks)."""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.db = self.SessionLocal()

        self.private_key, self.jwks = generate_keypair()
        patch_jwks(self, self.jwks)

    def tearDown(self):
        self.db.close()

    def test_missing_authorization_header_raises_401(self):
        with self.assertRaises(HTTPException) as ctx:
            get_current_user(authorization=None, db=self.db)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_header_without_bearer_prefix_raises_401(self):
        with self.assertRaises(HTTPException) as ctx:
            get_current_user(authorization="Token abc123", db=self.db)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_missing_supabase_url_configuration_raises_503(self):
        with patch.dict("os.environ", {}, clear=True):
            token = make_token(sub="whatever", private_key=self.private_key)
            with self.assertRaises(HTTPException) as ctx:
                get_current_user(authorization=f"Bearer {token}", db=self.db)
            self.assertEqual(ctx.exception.status_code, 503)

    def test_malformed_token_raises_401(self):
        with self.assertRaises(HTTPException) as ctx:
            get_current_user(authorization="Bearer not-a-real-jwt", db=self.db)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_unknown_kid_raises_401(self):
        # Signed with a keypair/kid the mocked JWKS endpoint never serves -
        # simulates a token whose key this project genuinely doesn't know.
        other_private_key, _ = generate_keypair(kid="some-other-key")
        token = make_token(sub="user-x", private_key=other_private_key, kid="some-other-key")
        with self.assertRaises(HTTPException) as ctx:
            get_current_user(authorization=f"Bearer {token}", db=self.db)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_jwks_endpoint_unreachable_raises_503(self):
        with patch.object(
            PyJWKClient, "fetch_data", side_effect=PyJWKClientConnectionError("boom")
        ):
            auth_module._jwks_clients.pop(TEST_SUPABASE_URL, None)
            token = make_token(sub="user-x", private_key=self.private_key)
            with self.assertRaises(HTTPException) as ctx:
                get_current_user(authorization=f"Bearer {token}", db=self.db)
            self.assertEqual(ctx.exception.status_code, 503)

    def test_wrong_signature_raises_401(self):
        # Same kid as the mocked JWKS entry, but signed with a *different*
        # private key - the public key on file won't verify it.
        wrong_private_key, _ = generate_keypair()
        token = make_token(sub="user-x", private_key=wrong_private_key)
        with self.assertRaises(HTTPException) as ctx:
            get_current_user(authorization=f"Bearer {token}", db=self.db)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_expired_token_raises_401(self):
        token = make_token(sub="user-x", private_key=self.private_key, expires_delta=timedelta(hours=-1))
        with self.assertRaises(HTTPException) as ctx:
            get_current_user(authorization=f"Bearer {token}", db=self.db)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_wrong_audience_raises_401(self):
        token = make_token(sub="user-x", private_key=self.private_key, audience="not-authenticated")
        with self.assertRaises(HTTPException) as ctx:
            get_current_user(authorization=f"Bearer {token}", db=self.db)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_missing_sub_claim_raises_401(self):
        token = make_token(sub=None, private_key=self.private_key)
        with self.assertRaises(HTTPException) as ctx:
            get_current_user(authorization=f"Bearer {token}", db=self.db)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_valid_token_new_user_is_provisioned_just_in_time(self):
        token = make_token(sub="supabase-uid-1", private_key=self.private_key, email="new@example.com")
        user = get_current_user(authorization=f"Bearer {token}", db=self.db)

        self.assertIsNotNone(user.id)
        self.assertEqual(user.external_auth_id, "supabase-uid-1")
        self.assertEqual(user.email, "new@example.com")

        all_users = self.db.query(User).all()
        self.assertEqual(len(all_users), 1)

    def test_valid_token_existing_user_is_reused_not_duplicated(self):
        token = make_token(sub="supabase-uid-2", private_key=self.private_key, email="existing@example.com")
        first = get_current_user(authorization=f"Bearer {token}", db=self.db)
        second = get_current_user(authorization=f"Bearer {token}", db=self.db)

        self.assertEqual(first.id, second.id)
        all_users = self.db.query(User).filter(User.external_auth_id == "supabase-uid-2").all()
        self.assertEqual(len(all_users), 1)

    def test_key_rotation_is_picked_up_via_automatic_refetch(self):
        """A new signing key appears in Supabase's JWKS (rotation) -
        get_current_user must accept a token signed with it on the very
        next request, with no restart, by refetching once when it meets an
        unfamiliar kid (PyJWKClient.get_signing_key's built-in retry)."""
        new_private_key, new_jwks = generate_keypair(kid="rotated-key")
        combined_jwks = {"keys": self.jwks["keys"] + new_jwks["keys"]}

        with patch.object(PyJWKClient, "fetch_data", side_effect=[self.jwks, combined_jwks]):
            auth_module._jwks_clients.pop(TEST_SUPABASE_URL, None)

            # Warm the cache with the pre-rotation key set (1st fetch).
            old_token = make_token(sub="user-old", private_key=self.private_key)
            get_current_user(authorization=f"Bearer {old_token}", db=self.db)

            # This kid isn't in the cached set yet - must trigger a
            # refetch (2nd fetch) rather than being rejected outright.
            new_token = make_token(sub="user-new", private_key=new_private_key, kid="rotated-key")
            user = get_current_user(authorization=f"Bearer {new_token}", db=self.db)
            self.assertEqual(user.external_auth_id, "user-new")


if __name__ == "__main__":
    unittest.main()
