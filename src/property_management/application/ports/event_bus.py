from abc import ABC, abstractmethod

from property_management.domain.events import DomainEvent


class EventBus(ABC):
    @abstractmethod
    async def publish(self, event: DomainEvent) -> None: ...
