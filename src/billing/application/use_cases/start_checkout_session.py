from datetime import datetime, timezone
from uuid import UUID, uuid4

import structlog

from billing.application.ports.billing_gateway import (
    BillingGateway,
    CheckoutSession,
)
from billing.application.ports.repositories.subscription_repository import (
    SubscriptionRepository,
)
from billing.application.use_cases.price_catalog import (
    Cadence,
    PriceCatalog,
)
from billing.domain.models.subscription import (
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
    SubscriptionType,
)

log = structlog.get_logger()


class StartCheckoutSession:
    """Starts a Stripe Checkout session for the org.

    If the org has no Subscription row yet, one is created in INACTIVE
    state with `stripe_customer_id` populated — the webhook fills in
    the rest on `checkout.session.completed`. This keeps the customer
    id persisted even if the user abandons the flow, so a second click
    reuses the same Stripe customer.

    The caller passes `billing_email` / `billing_name` directly (from
    the authenticated user on the route). Billing does not look up the
    Organization — that's an organizations-context concern and not
    needed to build a Stripe customer.
    """

    def __init__(
        self,
        *,
        subscription_repo: SubscriptionRepository,
        billing_gateway: BillingGateway,
        price_catalog: PriceCatalog,
        trial_period_days: int,
        checkout_success_url: str,
        checkout_cancel_url: str,
    ) -> None:
        self._subscriptions = subscription_repo
        self._gateway = billing_gateway
        self._prices = price_catalog
        self._trial_days = trial_period_days
        self._success_url = checkout_success_url
        self._cancel_url = checkout_cancel_url

    async def execute(
        self,
        *,
        organization_id: UUID,
        plan: SubscriptionPlan,
        cadence: Cadence,
        billing_email: str,
        billing_name: str,
    ) -> CheckoutSession:
        price_id = self._prices.price_id_for(plan=plan, cadence=cadence)

        subscription = await self._subscriptions.get_by_organization_id(organization_id)
        customer_id = subscription.stripe_customer_id if subscription else None

        if not customer_id:
            customer_id = await self._gateway.create_customer(
                org_id=organization_id,
                email=billing_email,
                name=billing_name or billing_email,
            )
            now = datetime.now(timezone.utc)
            if subscription is None:
                subscription = Subscription(
                    id=uuid4(),
                    organization_id=organization_id,
                    plan=SubscriptionPlan.FREEMIUM,
                    type=SubscriptionType.STRIPE,
                    status=SubscriptionStatus.INACTIVE,
                    stripe_customer_id=customer_id,
                    stripe_subscription_id=None,
                    stripe_price_id=None,
                    current_period_start=None,
                    current_period_end=None,
                    created_at=now,
                    updated_at=now,
                )
                subscription = await self._subscriptions.save(subscription)
            else:
                subscription.update(stripe_customer_id=customer_id)
                subscription = await self._subscriptions.update(subscription)

        session = await self._gateway.create_checkout_session(
            customer_id=customer_id,
            price_id=price_id,
            success_url=self._success_url,
            cancel_url=self._cancel_url,
            trial_days=self._trial_days,
        )

        log.info(
            "checkout_session_started",
            organization_id=str(organization_id),
            plan=plan.value,
            cadence=cadence,
            session_id=session.id,
        )
        return session
