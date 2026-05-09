"""SQSWorker handler for ENRICH_PROPERTY_REQUESTED.v1.

Pulls the property_id / force / requested_by_user_id from the command
payload and dispatches to the orchestrator (`EnrichProperty`).
"""

from __future__ import annotations

from uuid import UUID

import structlog

from properties.container import Container
from shared.events.base import DomainEvent

log = structlog.get_logger()


async def handle_enrich_property_requested(event: DomainEvent, container: Container) -> None:
    if container.enrich_property is None:
        log.error(
            "enrich_property.handler_no_use_case_wired",
            event_type=event.event_type,
            event_id=event.event_id,
        )
        return

    payload = event.data
    await container.enrich_property.execute(
        property_id=UUID(payload["property_id"]),
        force=bool(payload.get("force", False)),
        requested_by_user_id=UUID(payload["requested_by_user_id"]),
    )
