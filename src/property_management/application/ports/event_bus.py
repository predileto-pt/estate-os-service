from abc import ABC, abstractmethod


class EventBus(ABC):
    @abstractmethod
    async def publish(self, message: dict) -> None: ...
