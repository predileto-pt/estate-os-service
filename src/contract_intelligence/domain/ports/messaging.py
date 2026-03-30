from __future__ import annotations

from typing import Any, Protocol


class MessagePublisherPort(Protocol):
    async def publish(self, queue_url: str, message: dict[str, Any]) -> None: ...
