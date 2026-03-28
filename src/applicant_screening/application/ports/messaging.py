from abc import ABC, abstractmethod
from typing import Any


class MessagePublisher(ABC):
    @abstractmethod
    async def publish(self, queue_url: str, message: dict[str, Any]) -> None: ...


class MessageConsumer(ABC):
    @abstractmethod
    async def poll(self, queue_url: str, max_messages: int = 1) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def delete_message(self, queue_url: str, receipt_handle: str) -> None: ...
