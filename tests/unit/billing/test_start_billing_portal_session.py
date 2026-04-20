from datetime import datetime, timezone
from uuid import uuid4

import pytest

from billing.adapters.inmemory.inmemory_billing_gateway import (
    InMemoryBillingGateway,
)
from billing.adapters.inmemory.inmemory_subscription_repo import (
    InMemorySubscriptionRepository,
)
from billing.application.use_cases.start_billing_portal_session import (
    StartBillingPortalSession,
)
from billing.domain.exceptions import BillingCustomerMissingError
from billing.domain.models.subscription import (
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
    SubscriptionType,
)


@pytest.fixture
def gateway() -> InMemoryBillingGateway:
    return InMemoryBillingGateway()


@pytest.fixture
def subscription_repo():
    return InMemorySubscriptionRepository()


@pytest.fixture
def use_case(subscription_repo, gateway):
    return StartBillingPortalSession(
        subscription_repo=subscription_repo,
        billing_gateway=gateway,
        portal_return_url="http://app.test/dashboard/settings/subscriptions",
    )


async def test_no_subscription_raises(use_case):
    with pytest.raises(BillingCustomerMissingError):
        await use_case.execute(organization_id=uuid4())


async def test_subscription_without_customer_id_raises(use_case, subscription_repo):
    now = datetime.now(timezone.utc)
    org_id = uuid4()
    await subscription_repo.save(
        Subscription(
            id=uuid4(),
            organization_id=org_id,
            plan=SubscriptionPlan.FREEMIUM,
            type=SubscriptionType.MANUAL,
            status=SubscriptionStatus.ACTIVE,
            stripe_customer_id=None,
            stripe_subscription_id=None,
            stripe_price_id=None,
            current_period_start=now,
            current_period_end=None,
            created_at=now,
            updated_at=now,
        )
    )

    with pytest.raises(BillingCustomerMissingError):
        await use_case.execute(organization_id=org_id)


async def test_happy_path_returns_portal_url(use_case, subscription_repo, gateway):
    now = datetime.now(timezone.utc)
    org_id = uuid4()
    await subscription_repo.save(
        Subscription(
            id=uuid4(),
            organization_id=org_id,
            plan=SubscriptionPlan.PRO,
            type=SubscriptionType.STRIPE,
            status=SubscriptionStatus.ACTIVE,
            stripe_customer_id="cus_real_1",
            stripe_subscription_id="sub_real_1",
            stripe_price_id="price_pm",
            current_period_start=now,
            current_period_end=None,
            created_at=now,
            updated_at=now,
        )
    )

    url = await use_case.execute(organization_id=org_id)

    assert url.startswith("https://portal.stripe.test/")
    assert len(gateway.portals) == 1
    assert gateway.portals[0].customer_id == "cus_real_1"
    assert gateway.portals[0].return_url == "http://app.test/dashboard/settings/subscriptions"
