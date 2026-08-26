"""Server-side calls to Supabase's Admin REST API.

Uses the service_role key, which bypasses row-level security entirely - this
module must only ever run in backend code, never be reachable from the
frontend build (see config.SUPABASE_SERVICE_ROLE_KEY_ENV).
"""
from __future__ import annotations

import os
import urllib.error
import urllib.request

from fastapi import HTTPException

from .config import SUPABASE_SERVICE_ROLE_KEY_ENV, SUPABASE_URL_ENV

_REQUEST_TIMEOUT_SECONDS = 15

_ACCOUNT_DELETION_FAILURE_DETAIL = (
    "Failed to delete the authentication account. Local account data was "
    "already removed; if you cannot sign up again with this email, contact "
    "support."
)


def delete_supabase_auth_user(external_auth_id: str) -> None:
    """Deletes a user from Supabase Auth via the Admin API.

    Called only AFTER the corresponding local account and all of its owned
    data have already been deleted (see account_deletion.py) - deliberately
    last in that sequence, so a failure here leaves the user locked out
    (safe direction) rather than leaving local data behind after their login
    identity is already gone.
    """
    supabase_url = os.getenv(SUPABASE_URL_ENV)
    service_role_key = os.getenv(SUPABASE_SERVICE_ROLE_KEY_ENV)
    if not supabase_url or not service_role_key:
        raise HTTPException(
            status_code=503,
            detail="Supabase admin access is not configured on this server.",
        )

    url = f"{supabase_url.rstrip('/')}/auth/v1/admin/users/{external_auth_id}"
    request = urllib.request.Request(
        url,
        method="DELETE",
        headers={
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        # 404: the Supabase Auth user is already gone - treat as success so
        # retrying a previously-interrupted deletion doesn't get stuck here.
        if exc.code == 404:
            return
        raise HTTPException(
            status_code=502, detail=_ACCOUNT_DELETION_FAILURE_DETAIL
        ) from exc
    except urllib.error.URLError as exc:
        raise HTTPException(
            status_code=502, detail=_ACCOUNT_DELETION_FAILURE_DETAIL
        ) from exc
