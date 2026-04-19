from uuid import UUID

from organizations.application.ports.repositories.subscription_repository import (
    SubscriptionRepository,
)
from organizations.domain.models.subscription import Subscription


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

    async def save(self, subscription: Subscription) -> Subscription:
        self._subscriptions[subscription.id] = subscription
        return subscription

    async def update(self, subscription: Subscription) -> Subscription:
        self._subscriptions[subscription.id] = subscription
        return subscription
