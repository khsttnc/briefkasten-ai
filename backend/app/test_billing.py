import hashlib
import hmac
import json
import time
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .billing import process_stripe_webhook
from .models import Base, ProcessedStripeEvent, Subscription, User

TEST_WEBHOOK_SECRET = "whsec_test_secret"


def _sign(payload_bytes: bytes, secret: str = TEST_WEBHOOK_SECRET, timestamp: int | None = None) -> str:
    """Reproduces Stripe's documented webhook signature scheme (HMAC-SHA256
    over "{timestamp}.{payload}") without depending on a real Stripe
    account or mocking stripe.Webhook.construct_event - this exercises the
    real verification path."""
    ts = timestamp if timestamp is not None else int(time.time())
    signed_payload = f"{ts}.{payload_bytes.decode()}".encode()
    signature = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={signature}"


def _event_payload(event_id: str, event_type: str, obj: dict) -> bytes:
    return json.dumps({"id": event_id, "type": event_type, "data": {"object": obj}}).encode()


class StripeWebhookTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.db = self.SessionLocal()

        self.user = User(external_auth_id="user-a", email="a@example.com")
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

        self.env_patcher = patch.dict("os.environ", {"STRIPE_WEBHOOK_SECRET": TEST_WEBHOOK_SECRET})
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        self.db.close()

    def test_missing_webhook_secret_configuration_raises_503(self):
        self.env_patcher.stop()
        with patch.dict("os.environ", {}, clear=True):
            payload = _event_payload("evt_1", "checkout.session.completed", {})
            with self.assertRaises(HTTPException) as ctx:
                process_stripe_webhook(payload, _sign(payload), self.db)
            self.assertEqual(ctx.exception.status_code, 503)
        self.env_patcher.start()

    def test_invalid_signature_raises_400_and_makes_no_changes(self):
        payload = _event_payload("evt_bad_sig", "checkout.session.completed", {})
        with self.assertRaises(HTTPException) as ctx:
            process_stripe_webhook(payload, "t=1,v1=deadbeef", self.db)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(self.db.query(ProcessedStripeEvent).count(), 0)
        self.assertEqual(self.db.query(Subscription).count(), 0)

    def test_checkout_session_completed_creates_subscription(self):
        payload = _event_payload(
            "evt_checkout_1",
            "checkout.session.completed",
            {
                "client_reference_id": str(self.user.id),
                "customer": "cus_123",
                "subscription": "sub_123",
            },
        )
        result = process_stripe_webhook(payload, _sign(payload), self.db)
        self.assertEqual(result["status"], "ok")

        subscription = self.db.query(Subscription).filter(Subscription.user_id == self.user.id).first()
        self.assertIsNotNone(subscription)
        self.assertEqual(subscription.stripe_customer_id, "cus_123")
        self.assertEqual(subscription.stripe_subscription_id, "sub_123")
        self.assertEqual(subscription.status, "active")
        self.assertEqual(subscription.plan, "pro")

    def test_checkout_session_completed_without_client_reference_id_is_ignored(self):
        payload = _event_payload(
            "evt_checkout_no_ref", "checkout.session.completed",
            {"customer": "cus_999", "subscription": "sub_999"},
        )
        result = process_stripe_webhook(payload, _sign(payload), self.db)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(self.db.query(Subscription).count(), 0)

    def test_duplicate_event_id_is_processed_only_once(self):
        payload = _event_payload(
            "evt_dup_1", "checkout.session.completed",
            {"client_reference_id": str(self.user.id), "customer": "cus_1", "subscription": "sub_1"},
        )
        sig = _sign(payload)

        first = process_stripe_webhook(payload, sig, self.db)
        second = process_stripe_webhook(payload, sig, self.db)

        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "already_processed")
        self.assertEqual(
            self.db.query(ProcessedStripeEvent).filter(ProcessedStripeEvent.event_id == "evt_dup_1").count(),
            1,
        )
        self.assertEqual(self.db.query(Subscription).count(), 1)

    def test_subscription_updated_changes_status(self):
        checkout_payload = _event_payload(
            "evt_checkout_2", "checkout.session.completed",
            {"client_reference_id": str(self.user.id), "customer": "cus_2", "subscription": "sub_2"},
        )
        process_stripe_webhook(checkout_payload, _sign(checkout_payload), self.db)

        update_payload = _event_payload(
            "evt_update_1", "customer.subscription.updated",
            {"id": "sub_2", "status": "past_due", "current_period_end": 1893456000},
        )
        result = process_stripe_webhook(update_payload, _sign(update_payload), self.db)
        self.assertEqual(result["status"], "ok")

        subscription = self.db.query(Subscription).filter(Subscription.user_id == self.user.id).first()
        self.assertEqual(subscription.status, "past_due")
        self.assertIsNotNone(subscription.current_period_end)

    def test_subscription_deleted_marks_canceled(self):
        checkout_payload = _event_payload(
            "evt_checkout_3", "checkout.session.completed",
            {"client_reference_id": str(self.user.id), "customer": "cus_3", "subscription": "sub_3"},
        )
        process_stripe_webhook(checkout_payload, _sign(checkout_payload), self.db)

        delete_payload = _event_payload(
            "evt_delete_1", "customer.subscription.deleted", {"id": "sub_3"}
        )
        result = process_stripe_webhook(delete_payload, _sign(delete_payload), self.db)
        self.assertEqual(result["status"], "ok")

        subscription = self.db.query(Subscription).filter(Subscription.user_id == self.user.id).first()
        self.assertEqual(subscription.status, "canceled")

    def test_unhandled_event_type_is_acknowledged_without_error(self):
        payload = _event_payload("evt_unhandled_1", "invoice.payment_failed", {"id": "in_1"})
        result = process_stripe_webhook(payload, _sign(payload), self.db)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            self.db.query(ProcessedStripeEvent).filter(ProcessedStripeEvent.event_id == "evt_unhandled_1").count(),
            1,
        )

    def test_subscription_update_for_unknown_subscription_is_ignored(self):
        payload = _event_payload(
            "evt_update_unknown", "customer.subscription.updated",
            {"id": "sub_does_not_exist_locally", "status": "active"},
        )
        result = process_stripe_webhook(payload, _sign(payload), self.db)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(self.db.query(Subscription).count(), 0)


if __name__ == "__main__":
    unittest.main()
