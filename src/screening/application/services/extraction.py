from uuid import UUID

import logfire
import structlog

from screening.application.ports.extractor import DocumentExtractor
from screening.application.ports.unit_of_work import ScreeningUnitOfWork
from screening.domain import events
from screening.domain.exceptions import DocumentNotFoundError
from screening.domain.models import DocumentStatus, ExtractedData, ExtractionStatus
from shared.events.base import DomainEvent
from shared.events.ports import CommandPublisher
from shared.events.types import APPLICANT_SCREENING_REQUESTED_V1
from shared.ports.document_storage import DocumentStorage

logger = structlog.get_logger()


class ExtractionService:
    def __init__(
        self,
        uow: ScreeningUnitOfWork,
        storage: DocumentStorage,
        extractor: DocumentExtractor,
        command_publisher: CommandPublisher,
        screening_queue_url: str,
    ) -> None:
        self._uow = uow
        self._storage = storage
        self._extractor = extractor
        self._command_publisher = command_publisher
        self._screening_queue_url = screening_queue_url

    async def extract_document(self, document_id: UUID, applicant_id: UUID) -> None:
        with logfire.span(
            "extraction.extract_document",
            applicant_id=str(applicant_id),
            document_id=str(document_id),
        ):
            await self._do_extract(document_id, applicant_id)

    async def _do_extract(self, document_id: UUID, applicant_id: UUID) -> None:
        should_publish = False

        async with self._uow:
            document = await self._uow.documents.get_by_id(document_id)
            if not document:
                raise DocumentNotFoundError(str(document_id))

            # Dedup: skip if already extracted
            existing = await self._uow.extracted_data.get_by_document_id(document_id)
            if existing and existing.extraction_status == ExtractionStatus.SUCCESS:
                logger.info("extraction_skipped_dedup", document_id=str(document_id))
                return

            # Update status to extracting
            document.status = DocumentStatus.EXTRACTING
            await self._uow.documents.update(document)

            # Download file from S3 and extract (I/O outside the transaction scope is fine
            # because we already hold the session open; the actual external calls don't
            # participate in the DB transaction)
            file_bytes = await self._storage.download(document.s3_key)
            extracted_content = await self._extractor.extract(
                file_bytes, filename=document.original_filename
            )

            # Save extracted data
            extracted_data = ExtractedData(
                document_id=document_id,
                extracted_content=extracted_content,
                extraction_status=ExtractionStatus.SUCCESS,
            )
            await self._uow.extracted_data.save(extracted_data)

            # Update document status
            document.status = DocumentStatus.EXTRACTED
            document.reducto_document_id = extracted_content.get("document_id")
            await self._uow.documents.update(document)
            logger.info("document_extracted", document_id=str(document_id))

            # Check if all documents for this applicant are extracted
            all_documents = await self._uow.documents.get_by_applicant_id(applicant_id)
            all_extracted = all(doc.status == DocumentStatus.EXTRACTED for doc in all_documents)

            if all_extracted:
                event = events.documents_extracted(
                    applicant_id=applicant_id,
                    document_count=len(all_documents),
                )
                await self._uow.events.save(event)
                should_publish = True

            await self._uow.commit()

        # Publish SQS message AFTER the transaction is committed
        if should_publish:
            await self._command_publisher.send(
                self._screening_queue_url,
                DomainEvent(
                    event_type=APPLICANT_SCREENING_REQUESTED_V1,
                    data={"applicant_id": str(applicant_id)},
                ),
            )
            logger.info("all_documents_extracted", applicant_id=str(applicant_id))
