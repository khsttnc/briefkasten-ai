from __future__ import annotations

import os
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .config import SUPABASE_JWT_SECRET_ENV
from .database import get_db
from .models import User

JWT_ALGORITHM = "HS256"
JWT_AUDIENCE = "authenticated"


def _get_supabase_jwt_secret() -> str:
    secret = os.getenv(SUPABASE_JWT_SECRET_ENV)
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="Authentication is not configured on this server.",
        )
    return secret


def get_current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> User:
    """Verifies the Supabase Auth JWT on the request and resolves it to an
    internal User row, matched by the token's "sub" claim.

    Ownership/authorization decisions never trust anything from the request
    body or query params - only this dependency's return value (see
    services.py, which takes owner_id from here, never from the client)."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token.")

    token = authorization.removeprefix("Bearer ").strip()
    secret = _get_supabase_jwt_secret()

    try:
        payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM], audience=JWT_AUDIENCE)
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

    return user
