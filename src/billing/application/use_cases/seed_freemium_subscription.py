"""Seed the default freemium Subscription for a newly-created Organization.

Invoked by `organizations.RegisterAdminAccount` through the
`SeedFreemiumSubscription` callable Protocol. Writes a Subscription row
with `plan=FREEMIUM, type=MANUAL, status=ACTIVE, stripe_* = None`.

This is the only mutation billing performs on organization creation;
all subsequent state comes from Stripe webhooks via `HandleStripeWebhookEvent`.
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from billing.application.ports.repositories.subscription_repository import (
    SubscriptionRepository,
)
from billing.domain.models.subscription import (
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
    SubscriptionType,
)


class SeedFreemiumSubscriptionUseCase:
    def __init__(self, subscription_repo: SubscriptionRepository) -> None:
        self._subscriptions = subscription_repo

    async def __call__(self, *, organization_id: UUID) -> Subscription:
        now = datetime.now(timezone.utc)
        return await self._subscriptions.save(
            Subscription(
                id=uuid4(),
                organization_id=organization_id,
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
