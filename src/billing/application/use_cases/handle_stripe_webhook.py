"""Apply a Stripe webhook event to our Subscription row.

Contract with the caller (the webhook route):

* The route verifies the `Stripe-Signature` header and parses the event
  into a `StripeEventData` via `BillingGateway.verify_webhook`.
* This use case takes that normalised event, records it in the
  idempotency store, and applies side effects exactly once.
* Replays of the same `event.id` are a no-op (idempotency table).
* Unknown `event.type` values are logged and acknowledged — Stripe
  retries non-2xx responses, so we always return gracefully.
"""

from datetime import datetime, timezone

import structlog

from billing.application.ports.billing_gateway import StripeEventData
from billing.application.ports.repositories.stripe_webhook_events_repository import (
    StripeWebhookEventsRepository,
)
from billing.application.ports.repositories.subscription_repository import (
    SubscriptionRepository,
)
from billing.application.use_cases.price_catalog import PriceCatalog
from billing.domain.exceptions import UnknownStripePriceError
from billing.domain.models.subscription import (
    SubscriptionPlan,
    SubscriptionStatus,
    SubscriptionType,
)

log = structlog.get_logger()


def _utc_from_stripe_ts(ts: int | None) -> datetime | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _status_from_stripe(stripe_status: str) -> SubscriptionStatus:
    mapping = {
        "active": SubscriptionStatus.ACTIVE,
        "trialing": SubscriptionStatus.TRIALING,
        "past_due": SubscriptionStatus.PAST_DUE,
        "canceled": SubscriptionStatus.CANCELLED,
        "unpaid": SubscriptionStatus.PAST_DUE,
        "incomplete": SubscriptionStatus.INACTIVE,
        "incomplete_expired": SubscriptionStatus.INACTIVE,
        "paused": SubscriptionStatus.INACTIVE,
    }
    return mapping.get(stripe_status, SubscriptionStatus.INACTIVE)


class HandleStripeWebhookEvent:
    def __init__(
        self,
        *,
        subscription_repo: SubscriptionRepository,
        webhook_events_repo: StripeWebhookEventsRepository,
        price_catalog: PriceCatalog,
    ) -> None:
        self._subscriptions = subscription_repo
        self._events = webhook_events_repo
        self._prices = price_catalog

    async def execute(self, event: StripeEventData) -> None:
        is_new = await self._events.try_mark_processed(event_id=event.id, event_type=event.type)
        if not is_new:
            log.info("stripe_webhook.duplicate_ignored", event_id=event.id, type=event.type)
            return

        obj = event.data_object
        match event.type:
            case "checkout.session.completed":
                await self._on_checkout_completed(obj)
            case "customer.subscription.created" | "customer.subscription.updated":
                await self._on_subscription_upsert(obj)
            case "customer.subscription.deleted":
                await self._on_subscription_deleted(obj)
            case "invoice.payment_failed":
                await self._on_invoice_payment_failed(obj)
            case "invoice.paid":
                await self._on_invoice_paid(obj)
            case _:
                log.info("stripe_webhook.ignored", type=event.type, event_id=event.id)

    async def _on_checkout_completed(self, obj: dict) -> None:
        customer_id = obj.get("customer")
        if not customer_id:
            log.warning("stripe_webhook.checkout_missing_customer", session_id=obj.get("id"))
            return

        sub = await self._subscriptions.get_by_stripe_customer_id(customer_id)
        if sub is None:
            log.warning(
                "stripe_webhook.checkout_no_local_subscription",
                customer_id=customer_id,
            )
            return

        stripe_sub_id = obj.get("subscription")
        if stripe_sub_id and sub.stripe_subscription_id != stripe_sub_id:
            sub.update(stripe_subscription_id=stripe_sub_id)
            await self._subscriptions.update(sub)

    async def _on_subscription_upsert(self, obj: dict) -> None:
        customer_id = obj.get("customer")
        if not customer_id:
            return

        sub = await self._subscriptions.get_by_stripe_customer_id(customer_id)
        if sub is None:
            log.warning("stripe_webhook.subscription_no_local_row", customer_id=customer_id)
            return

        status = _status_from_stripe(obj.get("status", ""))

        items = (obj.get("items") or {}).get("data") or []
        price_id = items[0]["price"]["id"] if items else None
        plan: SubscriptionPlan | None = None
        if price_id:
            try:
                plan = self._prices.plan_for(price_id)
            except UnknownStripePriceError:
                log.warning("stripe_webhook.unknown_price_id", price_id=price_id)

        sub.update(
            plan=plan,
            type=SubscriptionType.STRIPE,
            status=status,
            stripe_subscription_id=obj.get("id"),
            stripe_price_id=price_id,
            current_period_start=_utc_from_stripe_ts(obj.get("current_period_start")),
            current_period_end=_utc_from_stripe_ts(obj.get("current_period_end")),
        )
        await self._subscriptions.update(sub)

    async def _on_subscription_deleted(self, obj: dict) -> None:
        customer_id = obj.get("customer")
        if not customer_id:
            return

        sub = await self._subscriptions.get_by_stripe_customer_id(customer_id)
        if sub is None:
            return

        sub.update(status=SubscriptionStatus.CANCELLED)
        await self._subscriptions.update(sub)

    async def _on_invoice_payment_failed(self, obj: dict) -> None:
        customer_id = obj.get("customer")
        if not customer_id:
            return

        sub = await self._subscriptions.get_by_stripe_customer_id(customer_id)
        if sub is None or sub.status == SubscriptionStatus.PAST_DUE:
            return

        sub.update(status=SubscriptionStatus.PAST_DUE)
        await self._subscriptions.update(sub)

    async def _on_invoice_paid(self, obj: dict) -> None:
        customer_id = obj.get("customer")
        if not customer_id:
            return

        sub = await self._subscriptions.get_by_stripe_customer_id(customer_id)
        if sub is None or sub.status != SubscriptionStatus.PAST_DUE:
            return

        sub.update(status=SubscriptionStatus.ACTIVE)
        await self._subscriptions.update(sub)
