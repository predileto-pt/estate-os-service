"""Stripe-backed billing gateway.

Wraps the synchronous `stripe` SDK. Blocking calls are dispatched to a
worker thread via `asyncio.to_thread` so FastAPI's event loop stays
responsive.
"""

import asyncio
from uuid import UUID

import stripe
from stripe import SignatureVerificationError as StripeSignatureError

from billing.application.ports.billing_gateway import (
    BillingGateway,
    CheckoutSession,
    SignatureVerificationError,
    StripeEventData,
)


class StripeBillingGateway(BillingGateway):
    def __init__(self, *, api_key: str, webhook_secret: str) -> None:
        self._api_key = api_key
        self._webhook_secret = webhook_secret
        stripe.api_key = api_key

    async def create_customer(self, *, org_id: UUID, email: str, name: str) -> str:
        def _create() -> str:
            customer = stripe.Customer.create(
                email=email,
                name=name,
                metadata={"organization_id": str(org_id)},
            )
            return customer.id

        return await asyncio.to_thread(_create)

    async def create_checkout_session(
        self,
        *,
        customer_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        trial_days: int,
    ) -> CheckoutSession:
        def _create() -> CheckoutSession:
            subscription_data: dict = {}
            if trial_days > 0:
                subscription_data["trial_period_days"] = trial_days

            session = stripe.checkout.Session.create(
                mode="subscription",
                customer=customer_id,
                line_items=[{"price": price_id, "quantity": 1}],
                success_url=success_url,
                cancel_url=cancel_url,
                subscription_data=subscription_data or None,
                allow_promotion_codes=True,
            )
            return CheckoutSession(id=session.id, url=session.url or "")

        return await asyncio.to_thread(_create)

    async def create_portal_session(self, *, customer_id: str, return_url: str) -> str:
        def _create() -> str:
            session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url,
            )
            return session.url

        return await asyncio.to_thread(_create)

    def verify_webhook(self, *, payload: bytes, signature: str) -> StripeEventData:
        try:
            event = stripe.Webhook.construct_event(payload, signature, self._webhook_secret)
        except (StripeSignatureError, ValueError) as exc:
            raise SignatureVerificationError(str(exc)) from exc

        # `event["data"]["object"]` is a `stripe.StripeObject`. Calling
        # `dict(...)` on it raises `KeyError: 0` because its iterator
        # protocol doesn't cooperate with `dict`'s constructor. The SDK's
        # public `to_dict()` recurses by default, so nested StripeObjects
        # (e.g. `items.data[0].price`) also become plain Python dicts/lists.
        return StripeEventData(
            id=event["id"],
            type=event["type"],
            data_object=event["data"]["object"].to_dict(),
        )
