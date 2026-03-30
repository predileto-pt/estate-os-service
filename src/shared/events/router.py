from collections import defaultdict
from collections.abc import Callable, Coroutine
from typing import Any

import structlog

from shared.events.base import DomainEvent

logger = structlog.get_logger()

HandlerFn = Callable[[dict[str, Any], Any], Coroutine[Any, Any, None]]


class EventRouter:
    def __init__(self) -> None:
        self._handlers: dict[str, list[HandlerFn]] = defaultdict(list)

    def on(self, event_type: str, handler: HandlerFn) -> None:
        self._handlers[event_type].append(handler)

    async def dispatch(self, event: DomainEvent, context: Any) -> None:
        handlers = self._handlers.get(event.event_type, [])
        if not handlers:
            logger.warning("no_handler_for_event", event_type=event.event_type)
            return

        for handler in handlers:
            try:
                await handler(event.data, context)
            except Exception:
                logger.exception(
                    "event_handler_failed",
                    event_type=event.event_type,
                    event_id=event.event_id,
                )
                raise
