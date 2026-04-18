from collections import defaultdict
from collections.abc import Callable, Coroutine
from typing import Any

import structlog

from shared.events.base import DomainEvent

logger = structlog.get_logger()

# Handlers take the full DomainEvent envelope, not just the payload dict.
# `event.event_type`, `event.event_id`, `event.occurred_at` are first-class
# inside handlers — no smuggling through structlog.contextvars.
HandlerFn = Callable[[DomainEvent, Any], Coroutine[Any, Any, None]]


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
                await handler(event, context)
            except Exception:
                logger.exception(
                    "event_handler_failed",
                    event_type=event.event_type,
                    event_id=event.event_id,
                )
                raise
