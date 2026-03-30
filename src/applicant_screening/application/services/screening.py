from datetime import UTC, datetime
from uuid import UUID

import logfire
import structlog

from applicant_screening.application.events import (
    ApplicantScreenedEvent,
    DocumentPayload,
    ScreeningResultPayload,
)
from applicant_screening.application.ports.repositories.applicant_repository import (
    ApplicantRepository,
)
from applicant_screening.application.ports.repositories.document_repository import (
    DocumentRepository,
)
from applicant_screening.application.ports.repositories.event_repository import EventRepository
from applicant_screening.application.ports.repositories.extracted_data_repository import (
    ExtractedDataRepository,
)
from applicant_screening.application.ports.repositories.screening_report_repository import (
    ScreeningReportRepository,
)
from applicant_screening.application.ports.repositories.submission_repository import (
    SubmissionRepository,
)
from applicant_screening.application.ports.screening import ScreeningAssessor
from applicant_screening.application.ports.translator import Translator
from applicant_screening.domain import events
from applicant_screening.domain.exceptions import ApplicantNotFoundError
from applicant_screening.domain.models.document import DocumentType
from applicant_screening.domain.models.submission import SubmissionStatus
from shared.events import DomainEvent, DomainEventPublisher

logger = structlog.get_logger()


class ScreeningService:
    def __init__(
        self,
        applicant_repo: ApplicantRepository,
        document_repo: DocumentRepository,
        extracted_data_repo: ExtractedDataRepository,
        report_repo: ScreeningReportRepository,
        assessor: ScreeningAssessor,
        event_repo: EventRepository,
        domain_event_publisher: DomainEventPublisher,
        submission_repo: SubmissionRepository | None = None,
        translator: Translator | None = None,
    ) -> None:
        self._applicant_repo = applicant_repo
        self._document_repo = document_repo
        self._extracted_data_repo = extracted_data_repo
        self._report_repo = report_repo
        self._assessor = assessor
        self._event_repo = event_repo
        self._domain_event_publisher = domain_event_publisher
        self._submission_repo = submission_repo
        self._translator = translator

    async def screen_applicant(self, applicant_id: UUID, *, force: bool = False) -> None:
        # Idempotency: skip if already screened (unless force=True for DLQ reprocessing)
        if not force:
            existing_report = await self._report_repo.get_by_applicant_id(applicant_id)
            if existing_report:
                logger.info("screening_skipped_dedup", applicant_id=str(applicant_id))
                return

        with logfire.span("screening.screen_applicant", applicant_id=str(applicant_id)):
            await self._do_screen(applicant_id)

    async def _do_screen(self, applicant_id: UUID) -> None:
        applicant = await self._applicant_repo.get_by_id(applicant_id)
        if not applicant:
            raise ApplicantNotFoundError(str(applicant_id))

        # Load all extracted data
        documents = await self._document_repo.get_by_applicant_id(applicant_id)
        extracted_data = []
        for doc in documents:
            data = await self._extracted_data_repo.get_by_document_id(doc.id)
            if data:
                extracted_data.append(data)

        # Run LangGraph screening
        report = await self._assessor.assess(applicant, extracted_data)

        # Translate justification to Portuguese
        if self._translator and report.justification:
            try:
                report.justification = await self._translator.translate(
                    report.justification, "European Portuguese (pt-PT)"
                )
            except Exception:
                logger.warning(
                    "translation_failed",
                    applicant_id=str(applicant_id),
                    exc_info=True,
                )

        report = await self._report_repo.save(report)
        logger.info(
            "screening_complete",
            applicant_id=str(applicant_id),
            risk_level=report.risk_level,
        )

        # Update Submission status to PROCESSED
        if self._submission_repo:
            submission = await self._submission_repo.get_by_applicant_id(applicant_id)
            if submission:
                submission.status = SubmissionStatus.PROCESSED
                await self._submission_repo.update(submission)
                logger.info("submission_processed", submission_id=str(submission.id))

        # Save event
        event = events.applicant_screened(
            applicant_id=applicant_id,
            risk_level=report.risk_level.value,
        )
        await self._event_repo.save(event)

        # Build enriched event for other services
        has_id_document = any(doc.document_type == DocumentType.ID_DOCUMENT for doc in documents)
        has_proof_of_income = any(
            doc.document_type == DocumentType.PROOF_OF_INCOME for doc in documents
        )

        screened_event = ApplicantScreenedEvent(
            applicant_id=applicant.id,
            form_request_id=applicant.form_request_id,
            organization_id=applicant.organization_id,
            name=applicant.name,
            email=applicant.email,
            date_of_birth=applicant.date_of_birth,
            listing_type=applicant.listing_type.value,
            property_type=applicant.property_type.value if applicant.property_type else None,
            property_value=applicant.property_value,
            monthly_rent=applicant.monthly_rent,
            has_id_document=has_id_document,
            has_proof_of_income=has_proof_of_income,
            documents=[
                DocumentPayload(
                    document_type=doc.document_type.value,
                    s3_key=doc.s3_key,
                    original_filename=doc.original_filename,
                )
                for doc in documents
            ],
            screening=ScreeningResultPayload(
                risk_level=report.risk_level.value,
                identity_verified=report.identity_verified,
                income_verified=report.income_verified,
                dti_ratio=report.dti_ratio,
                justification=report.justification,
                average_monthly_income=report.average_monthly_income,
            ),
            screened_at=datetime.now(UTC),
        )

        await self._domain_event_publisher.publish(
            DomainEvent(
                event_type="APPLICANT_SCREENED",
                data=screened_event.model_dump(mode="json"),
            )
        )
