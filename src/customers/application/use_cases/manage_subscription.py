from datetime import datetime, timezone
from uuid import UUID, uuid4

import structlog

from customers.application.ports.repositories.subscription_repository import (
    SubscriptionRepository,
)
from customers.domain.exceptions import SubscriptionNotFoundError
from customers.domain.models.subscription import (
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
    SubscriptionType,
)

log = structlog.get_logger()


class CreateSubscription:
    def __init__(
        self,
        subscription_repo: SubscriptionRepository,
    ) -> None:
        self.subscription_repo = subscription_repo

    async def execute(
        self,
        *,
        organization_id: UUID,
        plan: SubscriptionPlan,
        type: SubscriptionType,
        status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
        stripe_subscription_id: str | None = None,
        stripe_price_id: str | None = None,
        current_period_start: datetime | None = None,
        current_period_end: datetime | None = None,
    ) -> Subscription:
        now = datetime.now(timezone.utc)
        subscription = Subscription(
            id=uuid4(),
            organization_id=organization_id,
            plan=plan,
            type=type,
            status=status,
            stripe_subscription_id=stripe_subscription_id,
            stripe_price_id=stripe_price_id,
            current_period_start=current_period_start or now,
            current_period_end=current_period_end,
            created_at=now,
            updated_at=now,
        )
        subscription = await self.subscription_repo.save(subscription)

        log.info("subscription_created", subscription_id=str(subscription.id))
        return subscription


class UpdateSubscription:
    def __init__(
        self,
        subscription_repo: SubscriptionRepository,
    ) -> None:
        self.subscription_repo = subscription_repo

    async def execute(
        self,
        *,
        subscription_id: UUID,
        status: SubscriptionStatus | None = None,
        stripe_subscription_id: str | None = None,
        stripe_price_id: str | None = None,
        current_period_start: datetime | None = None,
        current_period_end: datetime | None = None,
    ) -> Subscription:
        subscription = await self.subscription_repo.get_by_id(subscription_id)
        if not subscription:
            raise SubscriptionNotFoundError(str(subscription_id))

        subscription.update(
            status=status,
            stripe_subscription_id=stripe_subscription_id,
            stripe_price_id=stripe_price_id,
            current_period_start=current_period_start,
            current_period_end=current_period_end,
        )

        subscription = await self.subscription_repo.update(subscription)

        log.info("subscription_updated", subscription_id=str(subscription.id))
        return subscription
