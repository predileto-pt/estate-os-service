from abc import ABC, abstractmethod

from shared.events.base import DomainEvent


class DomainEventPublisher(ABC):
    @abstractmethod
    async def publish(self, event: DomainEvent) -> None: ...
