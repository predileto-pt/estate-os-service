"""Billing gateway port — abstraction over the payment provider.

Hides Stripe (or any future provider) from business code. Use cases
depend on this Protocol; the production adapter is Stripe-backed, and
tests use an in-memory double.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class CheckoutSession:
    id: str
    url: str


@dataclass(frozen=True)
class StripeEventData:
    """Normalised view of a Stripe event payload.

    Carries the fields the webhook handler needs for routing + the full
    decoded envelope for audit / idempotency storage. Keeps the handler
    independent of Stripe's concrete `Event` object shape so unit tests
    can emit these directly without touching the SDK.
    """

    id: str
    type: str
    data_object: dict
    raw_payload: dict  # full event envelope, preserved for audit


class SignatureVerificationError(Exception):
    """Raised when the Stripe-Signature header does not match the
    computed HMAC of the raw request body."""


class BillingGateway(Protocol):
    async def create_customer(self, *, org_id: UUID, email: str, name: str) -> str: ...

    async def create_checkout_session(
        self,
        *,
        customer_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        trial_days: int,
    ) -> CheckoutSession: ...

    async def create_portal_session(self, *, customer_id: str, return_url: str) -> str: ...

    async def get_subscription(self, *, subscription_id: str) -> dict:
        """Retrieve a Stripe subscription as a plain dict.

        Used by the webhook handler to provision the plan from
        `checkout.session.completed` (whose payload carries only the
        subscription id, not its price/status), so the upgrade no longer
        depends on `customer.subscription.*` events being delivered.
        """
        ...

    def verify_webhook(self, *, payload: bytes, signature: str) -> StripeEventData: ...
