from uuid import UUID

import structlog

from shared.events.base import DomainEvent

logger = structlog.get_logger()


async def handle_document_ingestion_requested(event: DomainEvent, container) -> None:
    document_id = UUID(event.data["document_id"])
    logger.info("ingestion_event_received", document_id=str(document_id))
    await container.ingestion_service.ingest(document_id)
