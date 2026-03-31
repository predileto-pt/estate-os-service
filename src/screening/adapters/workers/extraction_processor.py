from uuid import UUID

import structlog

logger = structlog.get_logger()


async def process_event(message_body: dict, container) -> None:
    document_id = UUID(message_body["document_id"])
    applicant_id = UUID(message_body["applicant_id"])
    logger.info(
        "extraction_event_received", document_id=str(document_id), applicant_id=str(applicant_id)
    )
    await container.extraction_service.extract_document(document_id, applicant_id)
