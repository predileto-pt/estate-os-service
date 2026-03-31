from uuid import UUID

import logfire
import structlog
from sqlalchemy.exc import IntegrityError

from screening.application.ports.messaging import MessagePublisher
from screening.application.ports.unit_of_work import ScreeningUnitOfWork
from screening.domain import events
from screening.domain.exceptions import DocumentLimitExceededError, DuplicateApplicantError
from screening.domain.models import (
    Applicant,
    Document,
    DocumentStatus,
    ListingType,
    PropertyType,
    Submission,
    SubmissionStatus,
)
from shared.ports.document_storage import DocumentStorage

logger = structlog.get_logger()


class SubmissionService:
    def __init__(
        self,
        uow: ScreeningUnitOfWork,
        storage: DocumentStorage,
        publisher: MessagePublisher,
        extraction_queue_url: str,
        max_documents: int = 5,
    ) -> None:
        self._uow = uow
        self._storage = storage
        self._publisher = publisher
        self._extraction_queue_url = extraction_queue_url
        self._max_documents = max_documents

    async def submit(
        self,
        nif: str,
        name: str,
        date_of_birth: str,
        email: str,
        organization_id: UUID,
        form_request_id: UUID,
        listing_type: ListingType,
        property_type: PropertyType,
        terms_accepted: bool,
        documents: list[dict],
        phone: str | None = None,
        property_value: float | None = None,
        monthly_rent: float | None = None,
        property_title: str = "n/a",
        property_address: str = "n/a",
    ) -> tuple[UUID, UUID, int]:
        if len(documents) > self._max_documents:
            raise DocumentLimitExceededError(self._max_documents)

        with logfire.span(
            "submission.submit",
            organization_id=str(organization_id),
            form_request_id=str(form_request_id),
            document_count=len(documents),
        ):
            return await self._do_submit(
                nif=nif,
                name=name,
                date_of_birth=date_of_birth,
                email=email,
                organization_id=organization_id,
                form_request_id=form_request_id,
                listing_type=listing_type,
                property_type=property_type,
                terms_accepted=terms_accepted,
                documents=documents,
                phone=phone,
                property_value=property_value,
                monthly_rent=monthly_rent,
                property_title=property_title,
                property_address=property_address,
            )

    async def _do_submit(
        self,
        nif: str,
        name: str,
        date_of_birth: str,
        email: str,
        organization_id: UUID,
        form_request_id: UUID,
        listing_type: ListingType,
        property_type: PropertyType,
        terms_accepted: bool,
        documents: list[dict],
        phone: str | None = None,
        property_value: float | None = None,
        monthly_rent: float | None = None,
        property_title: str = "n/a",
        property_address: str = "n/a",
    ) -> tuple[UUID, UUID, int]:
        from datetime import date

        doc_records: list[Document] = []

        async with self._uow:
            applicant = Applicant(
                nif=nif,
                name=name,
                date_of_birth=date.fromisoformat(date_of_birth)
                if isinstance(date_of_birth, str)
                else date_of_birth,
                email=email,
                organization_id=organization_id,
                form_request_id=form_request_id,
                listing_type=listing_type,
                property_type=property_type,
                phone=phone,
                property_value=property_value,
                monthly_rent=monthly_rent,
                property_title=property_title,
                property_address=property_address,
            )
            try:
                applicant = await self._uow.applicants.save(applicant)
            except IntegrityError as e:
                if "uq_applicants_nif_form_request" in str(e):
                    raise DuplicateApplicantError from e
                raise
            logger.info("applicant_created", applicant_id=str(applicant.id))

            # Create Submission record linking applicant to form request
            submission = Submission(
                form_request_id=form_request_id,
                organization_id=organization_id,
                applicant_id=applicant.id,
                terms_accepted=terms_accepted,
                status=SubmissionStatus.PENDING,
            )
            submission = await self._uow.submissions.save(submission)
            logger.info("submission_created", submission_id=str(submission.id))

            for doc_spec in documents:
                s3_key = doc_spec["s3_key"]
                document = Document(
                    applicant_id=applicant.id,
                    s3_key=s3_key,
                    original_filename=doc_spec["filename"],
                    content_type=doc_spec["content_type"],
                    document_type=doc_spec["document_type"],
                    status=DocumentStatus.UPLOADED,
                )
                document = await self._uow.documents.save(document)
                doc_records.append(document)
                logger.info("document_registered", document_id=str(document.id), s3_key=s3_key)

            # Update Submission status to PROCESSING
            submission.status = SubmissionStatus.PROCESSING
            await self._uow.submissions.update(submission)

            event = events.applicant_submitted(
                applicant_id=applicant.id,
                document_count=len(doc_records),
            )
            await self._uow.events.save(event)

            await self._uow.commit()

        # Publish SQS messages AFTER the transaction is committed
        for document in doc_records:
            await self._publisher.publish(
                self._extraction_queue_url,
                {"document_id": str(document.id), "applicant_id": str(applicant.id)},
            )

        return applicant.id, submission.id, len(doc_records)
