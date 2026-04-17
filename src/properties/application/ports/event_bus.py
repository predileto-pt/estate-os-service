from abc import ABC, abstractmethod

from shared.events.base import DomainEvent


class EventBus(ABC):
    """Command-publish port for the properties context.

    Today wraps the legacy `SQSMessagePublisher`-style publisher that sends
    to the properties extraction queue. After ADR-008 lands in full,
    `shared.events.ports.CommandPublisher` replaces this interface.
    """

    @abstractmethod
    async def publish(self, event: DomainEvent) -> None: ...
