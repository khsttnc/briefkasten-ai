"""GDPR Art. 17 (right to erasure) account self-deletion.

Deletion order is deliberate, not incidental:

1. Cancel any active Stripe subscription immediately - first, so a
   Stripe-side failure aborts with the account still fully intact and
   retryable (nothing else has been touched yet).
2. Delete every uploaded file from disk - all-or-nothing: any unexpected
   failure aborts before a single database row is deleted, so the account
   is never left half-deleted (some documents gone from disk, all of them
   still listed in the DB, or vice versa). A file that is already missing
   is not an error.
3. Delete the local database rows (User, cascading via SQLAlchemy
   relationship cascades to Subscription, Document, and
   DocumentAIAnalysis) in one transaction.
4. Delete the Supabase Auth identity - deliberately LAST: if this step
   fails, the user has already lost local access (the safer failure
   direction) rather than keeping their login while their local data
   silently survives.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .billing import cancel_subscription_immediately
from .models import Document, Subscription, User
from .supabase_admin import delete_supabase_auth_user

logger = logging.getLogger("briefkasten")

# Any other status (active, trialing, past_due, unpaid, ...) is treated as
# needing cancellation - only a subscription already confirmed ended is
# safe to skip.
_ALREADY_ENDED_SUBSCRIPTION_STATUSES = {"canceled", "inactive"}


def _find_cancelable_subscription(user_id: int, db: Session) -> Optional[Subscription]:
    subscription = db.query(Subscription).filter(Subscription.user_id == user_id).first()
    if (
        subscription is not None
        and subscription.stripe_subscription_id is not None
        and subscription.status not in _ALREADY_ENDED_SUBSCRIPTION_STATUSES
    ):
        return subscription
    return None


def get_deletion_preview(user: User, db: Session) -> dict:
    """What deleting this account will remove - shown to the user before
    they confirm (see CLAUDE.md: destructive actions must be confirmed)."""
    document_count = db.query(Document).filter(Document.owner_id == user.id).count()
    cancelable_subscription = _find_cancelable_subscription(user.id, db)
    return {
        "document_count": document_count,
        "has_active_subscription": cancelable_subscription is not None,
        "subscription_plan": (
            cancelable_subscription.plan if cancelable_subscription is not None else None
        ),
    }


def delete_account(user: User, db: Session) -> None:
    """Permanently deletes a user's account and everything owned by it.

    Never logs email, filenames, or document content - only the user id and
    a document count (see the module docstring for the deletion order and
    why it's structured this way).
    """
    user_id = user.id
    external_auth_id = user.external_auth_id

    cancelable_subscription = _find_cancelable_subscription(user_id, db)
    if cancelable_subscription is not None:
        cancel_subscription_immediately(cancelable_subscription.stripe_subscription_id)
        # Committed immediately, independent of the deletion transaction
        # below, so a retry after a later failure in this function doesn't
        # try to cancel an already-canceled subscription again.
        cancelable_subscription.status = "canceled"
        db.add(cancelable_subscription)
        db.commit()

    documents = db.query(Document).filter(Document.owner_id == user_id).all()
    document_count = len(documents)
    for document in documents:
        try:
            os.remove(document.filepath)
        except FileNotFoundError:
            continue
        except OSError as exc:
            # Fail closed, before any database row is touched: the account
            # remains fully intact and the operation is safely retryable.
            raise HTTPException(
                status_code=500,
                detail="Failed to delete an uploaded file. No account data was deleted; please try again.",
            ) from exc

    db.delete(user)
    db.commit()

    delete_supabase_auth_user(external_auth_id)

    logger.info(
        "Account deletion completed: user_id=%s, documents_deleted=%d",
        user_id,
        document_count,
    )
