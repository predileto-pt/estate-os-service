from uuid import UUID

import structlog

from shared.events.base import DomainEvent

logger = structlog.get_logger()


async def handle_document_analysis_requested(event: DomainEvent, container) -> None:
    document_id = UUID(event.data["document_id"])
    logger.info("analysis_event_received", document_id=str(document_id))
    await container.section_analysis_service.analyze(document_id)
