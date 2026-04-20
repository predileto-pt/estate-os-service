from datetime import datetime, timezone
from uuid import uuid4

import pytest

from billing.adapters.inmemory.inmemory_billing_gateway import (
    InMemoryBillingGateway,
)
from billing.adapters.inmemory.inmemory_subscription_repo import (
    InMemorySubscriptionRepository,
)
from billing.application.use_cases.price_catalog import PriceCatalog
from billing.application.use_cases.start_checkout_session import (
    StartCheckoutSession,
)
from billing.domain.exceptions import UnknownStripePriceError
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
def gateway() -> InMemoryBillingGateway:
    return InMemoryBillingGateway()


@pytest.fixture
def subscription_repo():
    return InMemorySubscriptionRepository()


@pytest.fixture
def use_case(subscription_repo, gateway, catalog):
    return StartCheckoutSession(
        subscription_repo=subscription_repo,
        billing_gateway=gateway,
        price_catalog=catalog,
        trial_period_days=7,
        checkout_success_url="http://app.test/billing/return?session_id={CHECKOUT_SESSION_ID}",
        checkout_cancel_url="http://app.test/dashboard/settings/subscriptions?checkout=cancelled",
    )


async def test_fresh_org_creates_stripe_customer_and_checkout(use_case, gateway, subscription_repo):
    organization_id = uuid4()

    session = await use_case.execute(
        organization_id=organization_id,
        plan=SubscriptionPlan.PRO,
        cadence="monthly",
        billing_email="admin@example.com",
        billing_name="Admin User",
    )

    assert session.url.startswith("https://checkout.stripe.test/")
    assert len(gateway.customers) == 1
    assert gateway.customers[0].email == "admin@example.com"
    assert gateway.customers[0].org_id == organization_id

    assert len(gateway.checkouts) == 1
    call = gateway.checkouts[0]
    assert call.price_id == "price_pm"
    assert call.trial_days == 7
    assert call.success_url.endswith("session_id={CHECKOUT_SESSION_ID}")

    sub = await subscription_repo.get_by_organization_id(organization_id)
    assert sub is not None
    assert sub.stripe_customer_id is not None
    assert sub.stripe_customer_id.startswith("cus_test_")
    assert sub.status == SubscriptionStatus.INACTIVE


async def test_returning_org_reuses_stripe_customer(use_case, gateway, subscription_repo):
    organization_id = uuid4()
    now = datetime.now(timezone.utc)
    existing = Subscription(
        id=uuid4(),
        organization_id=organization_id,
        plan=SubscriptionPlan.FREEMIUM,
        type=SubscriptionType.STRIPE,
        status=SubscriptionStatus.INACTIVE,
        stripe_customer_id="cus_existing_1234",
        stripe_subscription_id=None,
        stripe_price_id=None,
        current_period_start=None,
        current_period_end=None,
        created_at=now,
        updated_at=now,
    )
    await subscription_repo.save(existing)

    await use_case.execute(
        organization_id=organization_id,
        plan=SubscriptionPlan.ENTERPRISE,
        cadence="yearly",
        billing_email="admin@example.com",
        billing_name="Admin User",
    )

    assert gateway.customers == []  # no new customer created
    assert len(gateway.checkouts) == 1
    assert gateway.checkouts[0].customer_id == "cus_existing_1234"
    assert gateway.checkouts[0].price_id == "price_ey"


async def test_unknown_plan_cadence_raises(use_case):
    with pytest.raises(UnknownStripePriceError):
        await use_case.execute(
            organization_id=uuid4(),
            plan=SubscriptionPlan.FREEMIUM,
            cadence="monthly",
            billing_email="admin@example.com",
            billing_name="Admin",
        )
