from datetime import datetime, timezone
from uuid import uuid4

from organizations.domain.models.organization import Organization
from billing.domain.models.subscription import (
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
    SubscriptionType,
)


def _make_organization(**overrides) -> Organization:
    now = datetime.now(timezone.utc)
    defaults = {
        "id": uuid4(),
        "created_by": uuid4(),
        "name": "Test Organization",
        "nif": "123456789",
        "address": "Rua do Teste 1, Lisboa",
        "created_at": now,
        "updated_at": now,
    }
    return Organization(**(defaults | overrides))


def _make_subscription(organization_id, **overrides) -> Subscription:
    now = datetime.now(timezone.utc)
    defaults = {
        "id": uuid4(),
        "organization_id": organization_id,
        "plan": SubscriptionPlan.FREEMIUM,
        "type": SubscriptionType.MANUAL,
        "status": SubscriptionStatus.ACTIVE,
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
        "stripe_price_id": None,
        "current_period_start": None,
        "current_period_end": None,
        "created_at": now,
        "updated_at": now,
    }
    return Subscription(**(defaults | overrides))


async def test_save_and_get_subscription(organization_repo, subscription_repo):
    org = await organization_repo.save(_make_organization())
    sub = _make_subscription(org.id)

    saved = await subscription_repo.save(sub)
    assert saved.id == sub.id
    assert saved.plan == SubscriptionPlan.FREEMIUM

    fetched = await subscription_repo.get_by_id(sub.id)
    assert fetched is not None
    assert fetched.id == sub.id
    assert fetched.status == SubscriptionStatus.ACTIVE


async def test_get_by_organization_id(organization_repo, subscription_repo):
    org = await organization_repo.save(_make_organization())
    sub = _make_subscription(org.id)
    await subscription_repo.save(sub)

    fetched = await subscription_repo.get_by_organization_id(org.id)
    assert fetched is not None
    assert fetched.id == sub.id


async def test_update_subscription_status(organization_repo, subscription_repo):
    org = await organization_repo.save(_make_organization())
    sub = _make_subscription(org.id)
    await subscription_repo.save(sub)

    sub.status = SubscriptionStatus.CANCELLED
    sub.plan = SubscriptionPlan.PRO
    updated = await subscription_repo.update(sub)

    assert updated.status == SubscriptionStatus.CANCELLED
    assert updated.plan == SubscriptionPlan.PRO

    fetched = await subscription_repo.get_by_id(sub.id)
    assert fetched.status == SubscriptionStatus.CANCELLED
