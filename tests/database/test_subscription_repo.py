from datetime import datetime, timezone
from uuid import uuid4

from core_api.domain.models.company import Company
from core_api.domain.models.subscription import (
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
    SubscriptionType,
)


def _make_company(**overrides) -> Company:
    now = datetime.now(timezone.utc)
    defaults = {
        "id": uuid4(),
        "user_id": uuid4(),
        "name": "Test Company",
        "nif": "123456789",
        "address": "Rua do Teste 1, Lisboa",
        "created_at": now,
        "updated_at": now,
    }
    return Company(**(defaults | overrides))


def _make_subscription(company_id, **overrides) -> Subscription:
    now = datetime.now(timezone.utc)
    defaults = {
        "id": uuid4(),
        "company_id": company_id,
        "plan": SubscriptionPlan.FREEMIUM,
        "type": SubscriptionType.MANUAL,
        "status": SubscriptionStatus.ACTIVE,
        "stripe_subscription_id": None,
        "stripe_price_id": None,
        "current_period_start": None,
        "current_period_end": None,
        "created_at": now,
        "updated_at": now,
    }
    return Subscription(**(defaults | overrides))


async def test_save_and_get_subscription(company_repo, subscription_repo):
    company = await company_repo.save(_make_company())
    sub = _make_subscription(company.id)

    saved = await subscription_repo.save(sub)
    assert saved.id == sub.id
    assert saved.plan == SubscriptionPlan.FREEMIUM

    fetched = await subscription_repo.get_by_id(sub.id)
    assert fetched is not None
    assert fetched.id == sub.id
    assert fetched.status == SubscriptionStatus.ACTIVE


async def test_get_by_company_id(company_repo, subscription_repo):
    company = await company_repo.save(_make_company())
    sub = _make_subscription(company.id)
    await subscription_repo.save(sub)

    fetched = await subscription_repo.get_by_company_id(company.id)
    assert fetched is not None
    assert fetched.id == sub.id


async def test_update_subscription_status(company_repo, subscription_repo):
    company = await company_repo.save(_make_company())
    sub = _make_subscription(company.id)
    await subscription_repo.save(sub)

    sub.status = SubscriptionStatus.CANCELLED
    sub.plan = SubscriptionPlan.PRO
    updated = await subscription_repo.update(sub)

    assert updated.status == SubscriptionStatus.CANCELLED
    assert updated.plan == SubscriptionPlan.PRO

    fetched = await subscription_repo.get_by_id(sub.id)
    assert fetched.status == SubscriptionStatus.CANCELLED
