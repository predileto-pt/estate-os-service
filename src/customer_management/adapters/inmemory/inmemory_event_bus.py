from customer_management.application.ports.event_bus import EventBus
from customer_management.domain.events import DomainEvent


class InMemoryEventBus(EventBus):
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.events.append(event)
