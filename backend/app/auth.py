from __future__ import annotations

import os
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException, Request
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError
from sqlalchemy.orm import Session

from .config import SUPABASE_URL_ENV
from .database import get_db
from .models import User

JWT_ALGORITHM = "ES256"
JWT_AUDIENCE = "authenticated"

# Keyed by SUPABASE_URL rather than a single bare singleton: each distinct
# URL gets its own PyJWKClient, and each client keeps its own 5-minute JWKS
# cache internally (PyJWKClient's cache_jwk_set), so this dict is what makes
# that cache survive across requests instead of being rebuilt (and refetched)
# on every call. On a key rotation, PyJWKClient.get_signing_key already
# refetches once and retries when the token's kid isn't in the cached set,
# so rotation is handled without any extra code here.
_jwks_clients: dict[str, PyJWKClient] = {}


def _get_jwks_client() -> PyJWKClient:
    supabase_url = os.getenv(SUPABASE_URL_ENV)
    if not supabase_url:
        raise HTTPException(
            status_code=503,
            detail="Authentication is not configured on this server.",
        )

    client = _jwks_clients.get(supabase_url)
    if client is None:
        jwks_uri = f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
        client = PyJWKClient(jwks_uri, cache_jwk_set=True, lifespan=300)
        _jwks_clients[supabase_url] = client
    return client


def get_current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
    request: Request = None,
) -> User:
    """Verifies the Supabase Auth JWT on the request and resolves it to an
    internal User row, matched by the token's "sub" claim.

    Tokens are ES256-signed with Supabase's asymmetric project key; the
    verifying public key is fetched (and cached) from Supabase's JWKS
    endpoint - see _get_jwks_client - rather than configured as a shared
    secret.

    Ownership/authorization decisions never trust anything from the request
    body or query params - only this dependency's return value (see
    services.py, which takes owner_id from here, never from the client).

    `request` is optional (default None) purely so existing unit tests can
    keep calling this function directly without a real Request object -
    FastAPI always injects the real one in production regardless of the
    default. When present, the resolved user's id is stashed on
    request.state so the rate limiter (see main.py) can key limits per
    authenticated user instead of falling back to per-IP."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token.")

    token = authorization.removeprefix("Bearer ").strip()
    jwks_client = _get_jwks_client()

    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)
    except PyJWKClientConnectionError:
        raise HTTPException(
            status_code=503,
            detail="Authentication service is temporarily unavailable.",
        )
    except (PyJWKClientError, jwt.InvalidTokenError):
        raise HTTPException(status_code=401, detail="Invalid token.")

    try:
        payload = jwt.decode(
            token, signing_key.key, algorithms=[JWT_ALGORITHM], audience=JWT_AUDIENCE
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token.")

    external_auth_id = payload.get("sub")
    if not external_auth_id:
        raise HTTPException(status_code=401, detail="Invalid token.")

    user = db.query(User).filter(User.external_auth_id == external_auth_id).first()
    if user is None:
        # Just-in-time provisioning: Supabase owns signup/login, so the
        # internal user row is created on this backend's first authenticated
        # request rather than via a separate registration step.
        user = User(external_auth_id=external_auth_id, email=payload.get("email"))
        db.add(user)
        db.commit()
        db.refresh(user)

    if request is not None:
        request.state.user_id = user.id

    return user
