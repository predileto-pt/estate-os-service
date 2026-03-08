from datetime import datetime, timezone
from uuid import UUID, uuid4

import structlog

from customer_management.application.ports.event_bus import EventBus
from customer_management.application.ports.repositories.subscription_repository import SubscriptionRepository
from customer_management.domain.events import SubscriptionCreated, SubscriptionUpdated
from customer_management.domain.exceptions import SubscriptionNotFoundError
from customer_management.domain.models.subscription import (
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
        event_bus: EventBus,
    ) -> None:
        self.subscription_repo = subscription_repo
        self.event_bus = event_bus

    async def execute(
        self,
        *,
        company_id: UUID,
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
            company_id=company_id,
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

        await self.event_bus.publish(
            SubscriptionCreated(
                subscription_id=subscription.id,
                company_id=company_id,
                plan=plan.value,
            )
        )

        log.info("subscription_created", subscription_id=str(subscription.id))
        return subscription


class UpdateSubscription:
    def __init__(
        self,
        subscription_repo: SubscriptionRepository,
        event_bus: EventBus,
    ) -> None:
        self.subscription_repo = subscription_repo
        self.event_bus = event_bus

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

        old_status = subscription.status.value

        if status is not None:
            subscription.status = status
        if stripe_subscription_id is not None:
            subscription.stripe_subscription_id = stripe_subscription_id
        if stripe_price_id is not None:
            subscription.stripe_price_id = stripe_price_id
        if current_period_start is not None:
            subscription.current_period_start = current_period_start
        if current_period_end is not None:
            subscription.current_period_end = current_period_end
        subscription.updated_at = datetime.now(timezone.utc)

        subscription = await self.subscription_repo.update(subscription)

        if status is not None:
            await self.event_bus.publish(
                SubscriptionUpdated(
                    subscription_id=subscription.id,
                    old_status=old_status,
                    new_status=subscription.status.value,
                )
            )

        log.info("subscription_updated", subscription_id=str(subscription.id))
        return subscription
