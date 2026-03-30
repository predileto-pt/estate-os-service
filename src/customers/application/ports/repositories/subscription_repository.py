from abc import ABC, abstractmethod
from uuid import UUID

from customers.domain.models.subscription import Subscription


class SubscriptionRepository(ABC):
    @abstractmethod
    async def get_by_id(self, subscription_id: UUID) -> Subscription | None: ...

    @abstractmethod
    async def get_by_organization_id(self, organization_id: UUID) -> Subscription | None: ...

    @abstractmethod
    async def save(self, subscription: Subscription) -> Subscription: ...

    @abstractmethod
    async def update(self, subscription: Subscription) -> Subscription: ...
