"""Unified domain events Lambda handler.

Processes SQS messages from the domain events queue and routes
to handlers registered from all bounded contexts.
"""

import json

import structlog

from shared.events.base import DomainEvent
from shared.entrypoints.events_worker import _build_context, _build_router

log = structlog.get_logger()

_router = None
_context = None


def handler(event, context):
    """SQS Lambda handler for domain events."""
    import asyncio

    asyncio.run(_handle(event))


async def _handle(event: dict) -> None:
    global _router, _context

    if _router is None:
        _router = _build_router()
    if _context is None:
        _context = await _build_context()

    for record in event["Records"]:
        body = json.loads(record["body"])
        domain_event = DomainEvent.from_dict(body)
        log.info(
            "lambda_domain_event_received",
            event_type=domain_event.event_type,
            event_id=domain_event.event_id,
        )
        await _router.dispatch(domain_event, _context)
        log.info(
            "lambda_domain_event_processed",
            event_type=domain_event.event_type,
            event_id=domain_event.event_id,
        )
