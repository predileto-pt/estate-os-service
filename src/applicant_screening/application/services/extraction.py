from uuid import UUID

import logfire
import structlog

from applicant_screening.application.ports.extractor import DocumentExtractor
from applicant_screening.application.ports.messaging import MessagePublisher
from applicant_screening.application.ports.repositories.document_repository import DocumentRepository
from applicant_screening.application.ports.repositories.event_repository import EventRepository
from applicant_screening.application.ports.repositories.extracted_data_repository import ExtractedDataRepository
from applicant_screening.domain import events
from applicant_screening.domain.exceptions import DocumentNotFoundError
from applicant_screening.domain.models import DocumentStatus, ExtractedData, ExtractionStatus
from shared.ports.document_storage import DocumentStorage

logger = structlog.get_logger()


class ExtractionService:
    def __init__(
        self,
        document_repo: DocumentRepository,
        extracted_data_repo: ExtractedDataRepository,
        storage: DocumentStorage,
        extractor: DocumentExtractor,
        publisher: MessagePublisher,
        event_repo: EventRepository,
        screening_queue_url: str,
    ) -> None:
        self._document_repo = document_repo
        self._extracted_data_repo = extracted_data_repo
        self._storage = storage
        self._extractor = extractor
        self._publisher = publisher
        self._event_repo = event_repo
        self._screening_queue_url = screening_queue_url

    async def extract_document(self, document_id: UUID, applicant_id: UUID) -> None:
        with logfire.span(
            "extraction.extract_document",
            applicant_id=str(applicant_id),
            document_id=str(document_id),
        ):
            await self._do_extract(document_id, applicant_id)

    async def _do_extract(self, document_id: UUID, applicant_id: UUID) -> None:
        document = await self._document_repo.get_by_id(document_id)
        if not document:
            raise DocumentNotFoundError(str(document_id))

        # Dedup: skip if already extracted
        existing = await self._extracted_data_repo.get_by_document_id(document_id)
        if existing and existing.extraction_status == ExtractionStatus.SUCCESS:
            logger.info("extraction_skipped_dedup", document_id=str(document_id))
            return

        # Update status to extracting
        document.status = DocumentStatus.EXTRACTING
        await self._document_repo.update(document)

        # Download file from S3 and extract
        file_bytes = await self._storage.download(document.s3_key)
        extracted_content = await self._extractor.extract(file_bytes, filename=document.original_filename)

        # Save extracted data
        extracted_data = ExtractedData(
            document_id=document_id,
            extracted_content=extracted_content,
            extraction_status=ExtractionStatus.SUCCESS,
        )
        await self._extracted_data_repo.save(extracted_data)

        # Update document status
        document.status = DocumentStatus.EXTRACTED
        document.reducto_document_id = extracted_content.get("document_id")
        await self._document_repo.update(document)
        logger.info("document_extracted", document_id=str(document_id))

        # Check if all documents for this applicant are extracted
        all_documents = await self._document_repo.get_by_applicant_id(applicant_id)
        all_extracted = all(doc.status == DocumentStatus.EXTRACTED for doc in all_documents)

        if all_extracted:
            await self._publisher.publish(
                self._screening_queue_url,
                {"applicant_id": str(applicant_id)},
            )
            event = events.documents_extracted(
                applicant_id=applicant_id,
                document_count=len(all_documents),
            )
            await self._event_repo.save(event)
            logger.info("all_documents_extracted", applicant_id=str(applicant_id))
