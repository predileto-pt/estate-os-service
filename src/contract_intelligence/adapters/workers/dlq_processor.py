from uuid import UUID

import structlog

from contract_intelligence.domain.entities.source_document import UploadStatus
from shared.events.base import DomainEvent

logger = structlog.get_logger()


async def handle_contract_document_dlq(event: DomainEvent, container) -> None:
    """Process a message routed to the contract_intelligence DLQ.

    The DLQ is the destination for messages that failed their main queue's
    retry budget. This handler reads the original command envelope (same
    shape as DOCUMENT_INGESTION_REQUESTED / DOCUMENT_ANALYSIS_REQUESTED)
    and marks the source document as permanently FAILED. Operators retry
    it manually via `source_document_service.retry_document`.
    """
    document_id_raw = event.data.get("document_id")
    if not document_id_raw:
        logger.warning("dlq_message_missing_document_id", data=event.data)
        return

    document_id = UUID(document_id_raw)
    repo = container.source_document_repo

    document = await repo.get_by_id(document_id)
    if document is None:
        logger.warning("dlq_document_not_found", document_id=str(document_id))
        return

    if document.upload_status == UploadStatus.FAILED:
        logger.warning("dlq_document_already_failed", document_id=str(document_id))
        return

    previous_status = document.upload_status
    document.mark_failed()
    await repo.update_status(document_id, document.upload_status)
    logger.info(
        "dlq_document_marked_failed",
        document_id=str(document_id),
        previous_status=previous_status.value,
    )
