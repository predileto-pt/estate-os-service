from core_api.application.ports.event_bus import EventBus
from core_api.domain.events import DomainEvent


class InMemoryEventBus(EventBus):
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.events.append(event)
