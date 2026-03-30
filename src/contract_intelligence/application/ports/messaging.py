from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class MessagePublisherPort(ABC):
    @abstractmethod
    async def publish(self, queue_url: str, message: dict[str, Any]) -> None: ...
