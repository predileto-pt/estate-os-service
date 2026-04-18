from uuid import UUID

import structlog

from shared.events.base import DomainEvent

logger = structlog.get_logger()


async def handle_applicant_extraction_requested(event: DomainEvent, container) -> None:
    document_id = UUID(event.data["document_id"])
    applicant_id = UUID(event.data["applicant_id"])
    logger.info(
        "extraction_event_received",
        document_id=str(document_id),
        applicant_id=str(applicant_id),
    )
    await container.extraction_service.extract_document(document_id, applicant_id)
