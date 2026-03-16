from uuid import UUID

from customer_management.application.ports.repositories.subscription_repository import (
    SubscriptionRepository,
)
from customer_management.domain.models.subscription import Subscription


class InMemorySubscriptionRepository(SubscriptionRepository):
    def __init__(self) -> None:
        self._subscriptions: dict[UUID, Subscription] = {}

    async def get_by_id(self, subscription_id: UUID) -> Subscription | None:
        return self._subscriptions.get(subscription_id)

    async def get_by_company_id(self, company_id: UUID) -> Subscription | None:
        for sub in self._subscriptions.values():
            if sub.company_id == company_id:
                return sub
        return None

    async def save(self, subscription: Subscription) -> Subscription:
        self._subscriptions[subscription.id] = subscription
        return subscription

    async def update(self, subscription: Subscription) -> Subscription:
        self._subscriptions[subscription.id] = subscription
        return subscription
