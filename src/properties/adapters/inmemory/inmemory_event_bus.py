from properties.application.ports.event_bus import EventBus
from shared.events.base import DomainEvent


class InMemoryEventBus(EventBus):
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.events.append(event)
