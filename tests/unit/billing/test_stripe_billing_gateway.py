"""Regression tests for `StripeBillingGateway.verify_webhook`.

Two bugs shipped here because the unit suite never exercised the
StripeObject → plain-dict conversion — `InMemoryBillingGateway` builds
`StripeEventData` with a plain dict directly, so the conversion path
only ever ran in production:

1. `dict(event["data"]["object"])` — raised KeyError: 0 at runtime.
2. `.to_dict_recursive()` — method doesn't exist on StripeObject.

These tests sign real payloads the way Stripe does and run them
through the actual `stripe.Webhook.construct_event` code path, so any
regression in `verify_webhook`'s conversion line fails CI immediately.
"""

import hashlib
import hmac
import json
import time

import pytest

from billing.adapters.outbound.stripe.billing_gateway import StripeBillingGateway
from billing.application.ports.billing_gateway import SignatureVerificationError

SECRET = "whsec_test_fixture"


def _sign(payload: bytes, secret: str) -> str:
    """Emulate Stripe's signing algorithm (see stripe-python WebhookSignature)."""
    timestamp = int(time.time())
    signed_payload = f"{timestamp}.{payload.decode()}".encode()
    signature = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


def test_verify_webhook_converts_nested_stripe_objects_to_plain_dict():
    gateway = StripeBillingGateway(api_key="sk_test_x", webhook_secret=SECRET)

    payload = json.dumps(
        {
            "id": "evt_test_123",
            "object": "event",
            "api_version": "2024-11-20.acacia",
            "type": "customer.subscription.created",
            "livemode": False,
            "created": int(time.time()),
            "pending_webhooks": 1,
            "request": {"id": None, "idempotency_key": None},
            "data": {
                "object": {
                    "id": "sub_test_1",
                    "object": "subscription",
                    "customer": "cus_test_1",
                    "status": "trialing",
                    "items": {
                        "object": "list",
                        "data": [{"price": {"id": "price_pro_monthly"}}],
                    },
                    "current_period_start": 1700000000,
                    "current_period_end": 1702592000,
                },
            },
        }
    ).encode()

    event = gateway.verify_webhook(payload=payload, signature=_sign(payload, SECRET))

    assert event.id == "evt_test_123"
    assert event.type == "customer.subscription.created"
    # The outer data_object must be a real Python dict, not a StripeObject.
    assert type(event.data_object) is dict
    # Nested StripeObjects must recurse into plain dicts/lists.
    assert type(event.data_object["items"]) is dict
    assert type(event.data_object["items"]["data"]) is list
    assert event.data_object["items"]["data"][0]["price"]["id"] == "price_pro_monthly"


def test_verify_webhook_raises_on_bad_signature():
    gateway = StripeBillingGateway(api_key="sk_test_x", webhook_secret=SECRET)

    with pytest.raises(SignatureVerificationError):
        gateway.verify_webhook(payload=b'{"id":"evt_1"}', signature="t=0,v1=deadbeef")
