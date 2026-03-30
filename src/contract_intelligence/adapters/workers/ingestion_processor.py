from uuid import UUID

import structlog

logger = structlog.get_logger()


async def process_event(body: dict, container) -> None:
    document_id = UUID(body["document_id"])
    logger.info("ingestion_event_received", document_id=str(document_id))
    await container.ingestion_service.ingest(document_id)
