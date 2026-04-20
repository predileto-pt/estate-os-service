from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from billing.adapters.database.models import SubscriptionModel
from billing.application.ports.repositories.subscription_repository import (
    SubscriptionRepository,
)
from billing.domain.models.subscription import (
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
    SubscriptionType,
)


class SqlAlchemySubscriptionRepository(SubscriptionRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_domain(m: SubscriptionModel) -> Subscription:
        return Subscription(
            id=UUID(m.id),
            organization_id=UUID(m.organization_id),
            plan=SubscriptionPlan(m.plan.value),
            type=SubscriptionType(m.type.value),
            status=SubscriptionStatus(m.status.value),
            stripe_customer_id=m.stripe_customer_id,
            stripe_subscription_id=m.stripe_subscription_id,
            stripe_price_id=m.stripe_price_id,
            current_period_start=m.current_period_start,
            current_period_end=m.current_period_end,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )

    @staticmethod
    def _strip_tz(dt: datetime | None) -> datetime | None:
        """Strip timezone info for TIMESTAMP WITHOUT TIME ZONE columns."""
        return dt.replace(tzinfo=None) if dt and dt.tzinfo else dt

    @classmethod
    def _to_model(cls, s: Subscription) -> SubscriptionModel:
        return SubscriptionModel(
            id=str(s.id),
            organization_id=str(s.organization_id),
            plan=s.plan.value,
            type=s.type.value,
            status=s.status.value,
            stripe_customer_id=s.stripe_customer_id,
            stripe_subscription_id=s.stripe_subscription_id,
            stripe_price_id=s.stripe_price_id,
            current_period_start=cls._strip_tz(s.current_period_start),
            current_period_end=cls._strip_tz(s.current_period_end),
        )

    async def get_by_id(self, subscription_id: UUID) -> Subscription | None:
        result = await self._session.execute(
            select(SubscriptionModel).where(SubscriptionModel.id == str(subscription_id))
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_organization_id(self, organization_id: UUID) -> Subscription | None:
        result = await self._session.execute(
            select(SubscriptionModel)
            .where(SubscriptionModel.organization_id == str(organization_id))
            .order_by(SubscriptionModel.created_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_stripe_customer_id(self, stripe_customer_id: str) -> Subscription | None:
        result = await self._session.execute(
            select(SubscriptionModel)
            .where(SubscriptionModel.stripe_customer_id == stripe_customer_id)
            .order_by(SubscriptionModel.created_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def save(self, subscription: Subscription) -> Subscription:
        model = self._to_model(subscription)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)

    async def update(self, subscription: Subscription) -> Subscription:
        result = await self._session.execute(
            select(SubscriptionModel).where(SubscriptionModel.id == str(subscription.id))
        )
        model = result.scalar_one()
        model.organization_id = str(subscription.organization_id)
        model.plan = subscription.plan.value
        model.type = subscription.type.value
        model.status = subscription.status.value
        model.stripe_customer_id = subscription.stripe_customer_id
        model.stripe_subscription_id = subscription.stripe_subscription_id
        model.stripe_price_id = subscription.stripe_price_id
        model.current_period_start = self._strip_tz(subscription.current_period_start)
        model.current_period_end = self._strip_tz(subscription.current_period_end)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)
