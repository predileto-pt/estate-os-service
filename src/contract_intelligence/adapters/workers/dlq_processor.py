from uuid import UUID

import structlog

from contract_intelligence.domain.entities.source_document import UploadStatus

logger = structlog.get_logger()


async def process_event(body: dict, container) -> None:
    document_id_raw = body.get("document_id")
    if not document_id_raw:
        logger.warning("dlq_message_missing_document_id", body=body)
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
