"""Apply a Stripe webhook event to our Subscription row.

Contract with the caller (the webhook route):

* The route verifies the `Stripe-Signature` header and parses the event
  into a `StripeEventData` via `BillingGateway.verify_webhook`.
* This use case takes that normalised event, applies its side effects,
  and only *then* records it in the idempotency store. If the apply
  raises, the event is left un-recorded so Stripe's retry re-runs it —
  a transient DB error or a misconfigured price never silently strands a
  paying customer on freemium.
* Replays of an already-recorded `event.id` are a no-op.
* Unknown `event.type` values are logged and acknowledged.

The plan upgrade is provisioned from BOTH `checkout.session.completed`
(authoritative — always delivered, fetches the subscription from Stripe)
and `customer.subscription.created/updated`, so the upgrade does not
depend on the `customer.subscription.*` events being subscribed on the
Stripe endpoint.
"""

from datetime import datetime, timezone

import structlog

from billing.application.ports.billing_gateway import BillingGateway, StripeEventData
from billing.application.ports.repositories.stripe_webhook_events_repository import (
    StripeWebhookEventsRepository,
)
from billing.application.ports.repositories.subscription_repository import (
    SubscriptionRepository,
)
from billing.application.use_cases.price_catalog import PriceCatalog
from billing.domain.exceptions import UnknownStripePriceError
from billing.domain.models.subscription import (
    Subscription,
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
        billing_gateway: BillingGateway,
    ) -> None:
        self._subscriptions = subscription_repo
        self._events = webhook_events_repo
        self._prices = price_catalog
        self._gateway = billing_gateway

    async def execute(self, event: StripeEventData) -> None:
        if await self._events.has_processed(event_id=event.id):
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

        # Record the event as processed only after side effects succeed.
        # If anything above raised (transient DB error, unknown price), we
        # never reach here — the event stays un-acked and Stripe retries it.
        await self._events.try_mark_processed(
            event_id=event.id,
            event_type=event.type,
            payload=event.raw_payload,
        )

    async def _apply_subscription(self, sub: Subscription, stripe_sub: dict) -> None:
        """Sync a Stripe subscription object onto our local row.

        Raises `UnknownStripePriceError` if the subscription's price is not
        in our catalog — surfacing loudly (and triggering a Stripe retry)
        rather than silently leaving the org on its previous plan. A blank
        price catalog or a test/live price-id mismatch is a config bug, not
        something to swallow.
        """
        items = (stripe_sub.get("items") or {}).get("data") or []
        price_id = items[0]["price"]["id"] if items else None
        if price_id is None:
            log.error(
                "stripe_webhook.subscription_without_price",
                subscription_id=stripe_sub.get("id"),
            )
            raise UnknownStripePriceError("subscription has no price")

        try:
            plan = self._prices.plan_for(price_id)
        except UnknownStripePriceError:
            log.error(
                "stripe_webhook.unknown_price_id",
                price_id=price_id,
                subscription_id=stripe_sub.get("id"),
            )
            raise

        status = _status_from_stripe(stripe_sub.get("status", ""))

        # Stripe's 2025 Clover API moved `current_period_{start,end}` off the
        # subscription object and onto each subscription item. Read top-level
        # first for older API versions, then fall back to items[0] for Clover.
        period_start = stripe_sub.get("current_period_start")
        period_end = stripe_sub.get("current_period_end")
        if items and (period_start is None or period_end is None):
            first_item = items[0]
            period_start = period_start or first_item.get("current_period_start")
            period_end = period_end or first_item.get("current_period_end")

        sub.update(
            plan=plan,
            type=SubscriptionType.STRIPE,
            status=status,
            stripe_subscription_id=stripe_sub.get("id"),
            stripe_price_id=price_id,
            current_period_start=_utc_from_stripe_ts(period_start),
            current_period_end=_utc_from_stripe_ts(period_end),
        )
        await self._subscriptions.update(sub)

    async def _on_checkout_completed(self, obj: dict) -> None:
        customer_id = obj.get("customer")
        if not customer_id:
            log.warning("stripe_webhook.checkout_missing_customer", session_id=obj.get("id"))
            return

        sub = await self._subscriptions.get_by_stripe_customer_id(customer_id)
        if sub is None:
            log.error(
                "stripe_webhook.checkout_no_local_subscription",
                customer_id=customer_id,
            )
            return

        stripe_sub_id = obj.get("subscription")
        if not stripe_sub_id:
            # Not a subscription checkout — nothing to provision.
            return

        # `checkout.session.completed` is always delivered and is our
        # authoritative provisioning signal: fetch the full subscription
        # (the session payload carries only the id) and apply the plan. This
        # upgrades the org even if `customer.subscription.*` events are not
        # subscribed on the Stripe endpoint.
        stripe_sub = await self._gateway.get_subscription(subscription_id=stripe_sub_id)
        await self._apply_subscription(sub, stripe_sub)

    async def _on_subscription_upsert(self, obj: dict) -> None:
        customer_id = obj.get("customer")
        if not customer_id:
            return

        sub = await self._subscriptions.get_by_stripe_customer_id(customer_id)
        if sub is None:
            log.error("stripe_webhook.subscription_no_local_row", customer_id=customer_id)
            return

        await self._apply_subscription(sub, obj)

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
