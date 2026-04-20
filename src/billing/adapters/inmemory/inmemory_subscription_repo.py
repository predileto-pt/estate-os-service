from uuid import UUID

from billing.application.ports.repositories.subscription_repository import (
    SubscriptionRepository,
)
from billing.domain.models.subscription import Subscription


class InMemorySubscriptionRepository(SubscriptionRepository):
    def __init__(self) -> None:
        self._subscriptions: dict[UUID, Subscription] = {}

    async def get_by_id(self, subscription_id: UUID) -> Subscription | None:
        return self._subscriptions.get(subscription_id)

    async def get_by_organization_id(self, organization_id: UUID) -> Subscription | None:
        for sub in self._subscriptions.values():
            if sub.organization_id == organization_id:
                return sub
        return None

    async def get_by_stripe_customer_id(self, stripe_customer_id: str) -> Subscription | None:
        for sub in self._subscriptions.values():
            if sub.stripe_customer_id == stripe_customer_id:
                return sub
        return None

    async def save(self, subscription: Subscription) -> Subscription:
        self._subscriptions[subscription.id] = subscription
        return subscription

    async def update(self, subscription: Subscription) -> Subscription:
        self._subscriptions[subscription.id] = subscription
        return subscription
