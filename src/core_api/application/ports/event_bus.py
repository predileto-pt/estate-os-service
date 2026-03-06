from abc import ABC, abstractmethod

from core_api.domain.events import DomainEvent


class EventBus(ABC):
    @abstractmethod
    async def publish(self, event: DomainEvent) -> None: ...
