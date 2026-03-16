from property_management.application.ports.event_bus import EventBus


class InMemoryEventBus(EventBus):
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def publish(self, message: dict) -> None:
        self.events.append(message)
