from abc import ABC, abstractmethod
from uuid import UUID

from customer_management.domain.models.subscription import Subscription


class SubscriptionRepository(ABC):
    @abstractmethod
    async def get_by_id(self, subscription_id: UUID) -> Subscription | None: ...

    @abstractmethod
    async def get_by_company_id(self, company_id: UUID) -> Subscription | None: ...

    @abstractmethod
    async def save(self, subscription: Subscription) -> Subscription: ...

    @abstractmethod
    async def update(self, subscription: Subscription) -> Subscription: ...
