from datetime import datetime, timezone
from uuid import uuid4

import pytest

from billing.adapters.inmemory.inmemory_stripe_webhook_events_repo import (
    InMemoryStripeWebhookEventsRepository,
)
from billing.adapters.inmemory.inmemory_subscription_repo import (
    InMemorySubscriptionRepository,
)
from billing.application.ports.billing_gateway import StripeEventData
from billing.application.use_cases.handle_stripe_webhook import (
    HandleStripeWebhookEvent,
)
from billing.application.use_cases.price_catalog import PriceCatalog
from billing.domain.models.subscription import (
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
    SubscriptionType,
)


@pytest.fixture
def catalog() -> PriceCatalog:
    return PriceCatalog(
        pro_monthly="price_pm",
        pro_yearly="price_py",
        enterprise_monthly="price_em",
        enterprise_yearly="price_ey",
    )


@pytest.fixture
def subscription_repo():
    return InMemorySubscriptionRepository()


@pytest.fixture
def webhook_events_repo():
    return InMemoryStripeWebhookEventsRepository()


@pytest.fixture
def use_case(subscription_repo, webhook_events_repo, catalog):
    return HandleStripeWebhookEvent(
        subscription_repo=subscription_repo,
        webhook_events_repo=webhook_events_repo,
        price_catalog=catalog,
    )


async def _seed_sub(
    subscription_repo,
    *,
    customer_id: str = "cus_123",
    status: SubscriptionStatus = SubscriptionStatus.INACTIVE,
    plan: SubscriptionPlan = SubscriptionPlan.FREEMIUM,
) -> Subscription:
    now = datetime.now(timezone.utc)
    sub = Subscription(
        id=uuid4(),
        organization_id=uuid4(),
        plan=plan,
        type=SubscriptionType.STRIPE,
        status=status,
        stripe_customer_id=customer_id,
        stripe_subscription_id=None,
        stripe_price_id=None,
        current_period_start=None,
        current_period_end=None,
        created_at=now,
        updated_at=now,
    )
    return await subscription_repo.save(sub)


def _event(event_type: str, obj: dict, event_id: str = "evt_1") -> StripeEventData:
    raw = {"id": event_id, "type": event_type, "data": {"object": obj}}
    return StripeEventData(id=event_id, type=event_type, data_object=obj, raw_payload=raw)


async def test_checkout_completed_sets_stripe_subscription_id(use_case, subscription_repo):
    sub = await _seed_sub(subscription_repo)

    await use_case.execute(
        _event(
            "checkout.session.completed",
            {"id": "cs_1", "customer": sub.stripe_customer_id, "subscription": "sub_1"},
        )
    )

    refreshed = await subscription_repo.get_by_organization_id(sub.organization_id)
    assert refreshed.stripe_subscription_id == "sub_1"


async def test_subscription_created_syncs_all_fields(use_case, subscription_repo):
    """Legacy API shape: current_period_{start,end} on the subscription object."""
    sub = await _seed_sub(subscription_repo)

    event_obj = {
        "id": "sub_stripe_1",
        "customer": sub.stripe_customer_id,
        "status": "trialing",
        "current_period_start": 1_700_000_000,
        "current_period_end": 1_700_600_000,
        "items": {"data": [{"price": {"id": "price_pm"}}]},
    }
    await use_case.execute(_event("customer.subscription.created", event_obj))

    refreshed = await subscription_repo.get_by_organization_id(sub.organization_id)
    assert refreshed.status == SubscriptionStatus.TRIALING
    assert refreshed.plan == SubscriptionPlan.PRO
    assert refreshed.stripe_price_id == "price_pm"
    assert refreshed.stripe_subscription_id == "sub_stripe_1"
    assert refreshed.current_period_start == datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)
    assert refreshed.current_period_end == datetime.fromtimestamp(1_700_600_000, tz=timezone.utc)


async def test_subscription_created_clover_api_reads_period_from_items(use_case, subscription_repo):
    """Stripe 2025 Clover API (e.g. 2026-02-25.clover) moved
    current_period_{start,end} off the subscription object and onto each
    subscription item. Top-level fields are null / missing; the handler
    must fall back to items[0]."""
    sub = await _seed_sub(subscription_repo)

    event_obj = {
        "id": "sub_stripe_1",
        "customer": sub.stripe_customer_id,
        "status": "trialing",
        # Top-level period fields are NOT set — this is what prod was seeing.
        "items": {
            "data": [
                {
                    "price": {"id": "price_pm"},
                    "current_period_start": 1_700_000_000,
                    "current_period_end": 1_700_600_000,
                }
            ]
        },
    }
    await use_case.execute(_event("customer.subscription.created", event_obj))

    refreshed = await subscription_repo.get_by_organization_id(sub.organization_id)
    assert refreshed.current_period_start == datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)
    assert refreshed.current_period_end == datetime.fromtimestamp(1_700_600_000, tz=timezone.utc)


async def test_subscription_created_top_level_wins_over_items(use_case, subscription_repo):
    """If both top-level and items[0] have period values, top-level wins.
    Guards against the fallback silently overriding a legacy-API value."""
    sub = await _seed_sub(subscription_repo)

    event_obj = {
        "id": "sub_stripe_1",
        "customer": sub.stripe_customer_id,
        "status": "trialing",
        "current_period_start": 1_700_000_000,
        "current_period_end": 1_700_600_000,
        "items": {
            "data": [
                {
                    "price": {"id": "price_pm"},
                    # Different values on the item — must be ignored.
                    "current_period_start": 9_999_999_999,
                    "current_period_end": 9_999_999_999,
                }
            ]
        },
    }
    await use_case.execute(_event("customer.subscription.created", event_obj))

    refreshed = await subscription_repo.get_by_organization_id(sub.organization_id)
    assert refreshed.current_period_start == datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)
    assert refreshed.current_period_end == datetime.fromtimestamp(1_700_600_000, tz=timezone.utc)


async def test_subscription_deleted_marks_cancelled(use_case, subscription_repo):
    sub = await _seed_sub(
        subscription_repo, status=SubscriptionStatus.ACTIVE, plan=SubscriptionPlan.PRO
    )

    await use_case.execute(
        _event(
            "customer.subscription.deleted",
            {"id": "sub_1", "customer": sub.stripe_customer_id, "status": "canceled"},
        )
    )

    refreshed = await subscription_repo.get_by_organization_id(sub.organization_id)
    assert refreshed.status == SubscriptionStatus.CANCELLED


async def test_invoice_payment_failed_marks_past_due(use_case, subscription_repo):
    sub = await _seed_sub(
        subscription_repo, status=SubscriptionStatus.ACTIVE, plan=SubscriptionPlan.PRO
    )

    await use_case.execute(
        _event(
            "invoice.payment_failed",
            {"id": "in_1", "customer": sub.stripe_customer_id},
        )
    )

    refreshed = await subscription_repo.get_by_organization_id(sub.organization_id)
    assert refreshed.status == SubscriptionStatus.PAST_DUE


async def test_invoice_paid_restores_past_due_to_active(use_case, subscription_repo):
    sub = await _seed_sub(
        subscription_repo, status=SubscriptionStatus.PAST_DUE, plan=SubscriptionPlan.PRO
    )

    await use_case.execute(
        _event(
            "invoice.paid",
            {"id": "in_2", "customer": sub.stripe_customer_id},
        )
    )

    refreshed = await subscription_repo.get_by_organization_id(sub.organization_id)
    assert refreshed.status == SubscriptionStatus.ACTIVE


async def test_invoice_paid_no_op_if_not_past_due(use_case, subscription_repo):
    sub = await _seed_sub(
        subscription_repo, status=SubscriptionStatus.ACTIVE, plan=SubscriptionPlan.PRO
    )

    await use_case.execute(
        _event(
            "invoice.paid",
            {"id": "in_3", "customer": sub.stripe_customer_id},
        )
    )

    refreshed = await subscription_repo.get_by_organization_id(sub.organization_id)
    assert refreshed.status == SubscriptionStatus.ACTIVE


async def test_webhook_event_payload_is_persisted(use_case, subscription_repo, webhook_events_repo):
    """Full raw payload should land on the events repo for audit."""
    sub = await _seed_sub(subscription_repo)

    event_obj = {"id": "cs_1", "customer": sub.stripe_customer_id, "subscription": "sub_1"}
    event = _event("checkout.session.completed", event_obj, event_id="evt_payload")

    await use_case.execute(event)

    # Private-ish peek at the in-memory repo to prove the payload round-tripped.
    stored_type, stored_payload = webhook_events_repo._seen["evt_payload"]
    assert stored_type == "checkout.session.completed"
    assert stored_payload == event.raw_payload
    assert stored_payload["data"]["object"]["customer"] == sub.stripe_customer_id


async def test_idempotency_same_event_id_is_noop(use_case, subscription_repo):
    sub = await _seed_sub(subscription_repo, status=SubscriptionStatus.ACTIVE)

    event = _event(
        "customer.subscription.deleted",
        {"id": "sub_1", "customer": sub.stripe_customer_id, "status": "canceled"},
        event_id="evt_dup",
    )

    await use_case.execute(event)
    # Reset status and replay the same event id — must not re-apply.
    refreshed = await subscription_repo.get_by_organization_id(sub.organization_id)
    refreshed.status = SubscriptionStatus.ACTIVE
    await subscription_repo.update(refreshed)

    await use_case.execute(event)
    refreshed = await subscription_repo.get_by_organization_id(sub.organization_id)
    assert refreshed.status == SubscriptionStatus.ACTIVE


async def test_unknown_event_type_is_ignored(use_case, subscription_repo):
    sub = await _seed_sub(subscription_repo, status=SubscriptionStatus.ACTIVE)

    await use_case.execute(
        _event("customer.discount.created", {"customer": sub.stripe_customer_id})
    )

    refreshed = await subscription_repo.get_by_organization_id(sub.organization_id)
    assert refreshed.status == SubscriptionStatus.ACTIVE


async def test_unknown_price_id_keeps_existing_plan(use_case, subscription_repo):
    sub = await _seed_sub(
        subscription_repo, status=SubscriptionStatus.ACTIVE, plan=SubscriptionPlan.PRO
    )

    await use_case.execute(
        _event(
            "customer.subscription.updated",
            {
                "id": "sub_1",
                "customer": sub.stripe_customer_id,
                "status": "active",
                "items": {"data": [{"price": {"id": "price_unknown"}}]},
            },
        )
    )

    refreshed = await subscription_repo.get_by_organization_id(sub.organization_id)
    assert refreshed.plan == SubscriptionPlan.PRO  # unchanged
    assert refreshed.stripe_price_id == "price_unknown"
