"""Shared ES256/JWKS test fixtures for auth-dependent test modules.

Not a test module itself (unittest discover's `test_*.py` pattern won't
pick this up), just the machinery test_auth.py / test_ownership.py /
test_documents_dashboard.py all need to fake a Supabase JWKS endpoint:
generate a throwaway EC keypair, sign tokens with it the way Supabase
does, and serve its public half back through PyJWKClient - with no real
network call.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey
from jwt.algorithms import ECAlgorithm
from unittest.mock import patch

from . import auth as auth_module

TEST_SUPABASE_URL = "https://test-project.supabase.co"
TEST_KID = "test-key-1"


def generate_keypair(kid: str = TEST_KID) -> tuple[EllipticCurvePrivateKey, dict]:
    """Returns (private_key, jwks_dict) for a fresh P-256 keypair - the
    private key signs test tokens, jwks_dict is what a mocked JWKS endpoint
    serves back for verification."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_jwk = ECAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    public_jwk["kid"] = kid
    public_jwk["use"] = "sig"
    public_jwk["alg"] = "ES256"
    return private_key, {"keys": [public_jwk]}


def make_token(
    sub: Optional[str],
    private_key: EllipticCurvePrivateKey,
    kid: str = TEST_KID,
    audience: str = auth_module.JWT_AUDIENCE,
    expires_delta: timedelta = timedelta(hours=1),
    email: Optional[str] = "",
) -> str:
    """sub=None omits the "sub" claim entirely (for testing that case),
    rather than encoding a literal null - real Supabase tokens never carry
    a null sub, they just wouldn't have the claim."""
    payload: dict[str, Any] = {
        "aud": audience,
        "exp": datetime.now(timezone.utc) + expires_delta,
    }
    if sub is not None:
        payload["sub"] = sub
    if email == "":
        payload["email"] = f"{sub}@example.com" if sub else None
    elif email is not None:
        payload["email"] = email
    return jwt.encode(payload, private_key, algorithm="ES256", headers={"kid": kid})


def patch_jwks(test_case, jwks_dict: dict, supabase_url: str = TEST_SUPABASE_URL) -> None:
    """Points auth.py at `supabase_url` and makes its JWKS client return
    `jwks_dict` with no real HTTP call. Call from a TestCase's setUp;
    cleanup (env var + this URL's cached PyJWKClient) is registered via
    test_case.addCleanup."""
    env_patcher = patch.dict("os.environ", {"SUPABASE_URL": supabase_url})
    env_patcher.start()
    test_case.addCleanup(env_patcher.stop)

    fetch_patcher = patch.object(
        auth_module.PyJWKClient, "fetch_data", return_value=jwks_dict
    )
    fetch_patcher.start()
    test_case.addCleanup(fetch_patcher.stop)

    # A client cached under this URL by an earlier test would still be
    # holding that test's cached JWK set, so this test's patched
    # fetch_data would never even get called - start every test with an
    # empty per-URL cache instead.
    auth_module._jwks_clients.pop(supabase_url, None)
    test_case.addCleanup(auth_module._jwks_clients.pop, supabase_url, None)
