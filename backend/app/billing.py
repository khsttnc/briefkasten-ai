from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict

import stripe
from fastapi import HTTPException
from sqlalchemy.orm import Session

from .config import STRIPE_SECRET_KEY_ENV, STRIPE_WEBHOOK_SECRET_ENV
from .models import ProcessedStripeEvent, Subscription, User

# Minimal event set for this phase - no product feature is gated on
# subscription status yet, this only keeps `subscriptions` in sync with
# Stripe. More event types (e.g. invoice.payment_failed) can be added later
# without changing this shape.
_HANDLED_EVENT_TYPES = {
    "checkout.session.completed",
    "customer.subscription.updated",
    "customer.subscription.deleted",
}


def _get_webhook_secret() -> str:
    secret = os.getenv(STRIPE_WEBHOOK_SECRET_ENV)
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="Stripe webhook is not configured on this server.",
        )
    return secret


def _get_stripe_api_key() -> str:
    api_key = os.getenv(STRIPE_SECRET_KEY_ENV)
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Stripe is not configured on this server.",
        )
    return api_key


def cancel_subscription_immediately(stripe_subscription_id: str) -> None:
    """Cancels a Stripe subscription right away (not at period end) - used
    when an account with an active paid subscription is deleted (see
    account_deletion.py). Raises HTTPException on any failure so the caller
    aborts the rest of account deletion instead of deleting local data while
    the user keeps being billed.
    """
    stripe.api_key = _get_stripe_api_key()
    try:
        stripe.Subscription.delete(stripe_subscription_id)
    except stripe.InvalidRequestError as exc:
        # Already canceled or already gone on Stripe's side - treat as
        # success so retrying a previously-interrupted account deletion
        # doesn't get stuck re-canceling something that no longer exists.
        if "No such subscription" not in str(exc):
            raise HTTPException(
                status_code=502, detail="Failed to cancel the Stripe subscription."
            ) from exc
    except stripe.StripeError as exc:
        raise HTTPException(
            status_code=502, detail="Failed to cancel the Stripe subscription."
        ) from exc


def process_stripe_webhook(payload: bytes, sig_header: str | None, db: Session) -> Dict[str, str]:
    """Verifies and applies one Stripe webhook delivery.

    Card/payment details never reach this function or this backend at all -
    Stripe Checkout is hosted, so only subscription status/metadata ever
    arrives here.
    """
    webhook_secret = _get_webhook_secret()

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(status_code=400, detail="Invalid Stripe signature.")

    # Note: this SDK version's Event/StripeObject is not a dict - no
    # .get()/[] dict-style access (it raises AttributeError telling you to
    # use .to_dict()). Everything below uses attribute access instead.
    event_id = event.id

    # Idempotency: Stripe explicitly documents that the same event may be
    # delivered more than once. Returning early here (without re-applying
    # the event) is what makes retried/duplicate deliveries safe.
    already_processed = (
        db.query(ProcessedStripeEvent).filter(ProcessedStripeEvent.event_id == event_id).first()
    )
    if already_processed is not None:
        return {"status": "already_processed"}

    if event.type in _HANDLED_EVENT_TYPES:
        _apply_event(db, event)

    # Recorded in the same commit as the subscription change (see
    # _apply_event) so a crash between the two can never happen - either
    # both land or neither does.
    db.add(ProcessedStripeEvent(event_id=event_id))
    db.commit()

    return {"status": "ok"}


def _get_or_create_subscription(db: Session, user_id: int) -> Subscription:
    subscription = db.query(Subscription).filter(Subscription.user_id == user_id).first()
    if subscription is None:
        subscription = Subscription(user_id=user_id)
        db.add(subscription)
    return subscription


def _apply_event(db: Session, event: Any) -> None:
    event_type = event.type
    obj = event.data.object

    if event_type == "checkout.session.completed":
        # The internal user id must be threaded through as
        # client_reference_id when the Checkout Session is created -
        # without it, this event cannot be mapped to a user and is ignored.
        internal_user_id = getattr(obj, "client_reference_id", None)
        if not internal_user_id:
            return
        user = db.query(User).filter(User.id == int(internal_user_id)).first()
        if user is None:
            return

        subscription = _get_or_create_subscription(db, user.id)
        subscription.stripe_customer_id = getattr(obj, "customer", None)
        subscription.stripe_subscription_id = getattr(obj, "subscription", None)
        subscription.status = "active"
        subscription.plan = "pro"
        return

    # customer.subscription.updated / customer.subscription.deleted both
    # carry the Stripe subscription id directly on the event object.
    stripe_subscription_id = getattr(obj, "id", None)
    subscription = (
        db.query(Subscription)
        .filter(Subscription.stripe_subscription_id == stripe_subscription_id)
        .first()
    )
    if subscription is None:
        # No local subscription to update yet (e.g. checkout.session.completed
        # for this subscription hasn't arrived/been processed) - nothing to do.
        return

    if event_type == "customer.subscription.updated":
        subscription.status = getattr(obj, "status", subscription.status)
        # NOTE: current_period_end's location on the Stripe object has
        # changed across API versions (top-level vs. per subscription item).
        # This reads the top-level field only - verify against the actual
        # Stripe API version in use before relying on this in production.
        current_period_end = getattr(obj, "current_period_end", None)
        if current_period_end:
            subscription.current_period_end = datetime.fromtimestamp(
                current_period_end, tz=timezone.utc
            )
    elif event_type == "customer.subscription.deleted":
        subscription.status = "canceled"
