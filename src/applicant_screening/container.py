from applicant_screening.application.ports.extractor import DocumentExtractor
from applicant_screening.application.ports.messaging import MessageConsumer, MessagePublisher
from applicant_screening.application.ports.repositories.applicant_repository import ApplicantRepository
from applicant_screening.application.ports.repositories.document_repository import DocumentRepository
from applicant_screening.application.ports.repositories.event_repository import EventRepository
from applicant_screening.application.ports.repositories.extracted_data_repository import ExtractedDataRepository
from applicant_screening.application.ports.repositories.intake_form_request_repository import (
    IntakeFormRequestRepository,
)
from applicant_screening.application.ports.repositories.screening_report_repository import ScreeningReportRepository
from applicant_screening.application.ports.repositories.submission_repository import SubmissionRepository
from applicant_screening.application.ports.screening import ScreeningAssessor
from applicant_screening.application.ports.translator import Translator
from applicant_screening.application.services.extraction import ExtractionService
from applicant_screening.application.services.screening import ScreeningService
from applicant_screening.application.services.submission import SubmissionService
from shared.ports.document_storage import DocumentStorage


class Container:
    def __init__(
        self,
        applicant_repo: ApplicantRepository,
        document_repo: DocumentRepository,
        extracted_data_repo: ExtractedDataRepository,
        screening_report_repo: ScreeningReportRepository,
        event_repo: EventRepository,
        intake_form_request_repo: IntakeFormRequestRepository,
        submission_repo: SubmissionRepository,
        document_storage: DocumentStorage,
        publisher: MessagePublisher,
        extractor: DocumentExtractor,
        assessor: ScreeningAssessor,
        extraction_queue_url: str,
        screening_queue_url: str,
        events_queue_url: str,
        max_documents: int = 5,
        consumer: MessageConsumer | None = None,
        translator: Translator | None = None,
    ) -> None:
        self.applicant_repo = applicant_repo
        self.document_repo = document_repo
        self.extracted_data_repo = extracted_data_repo
        self.screening_report_repo = screening_report_repo
        self.event_repo = event_repo
        self.intake_form_request_repo = intake_form_request_repo
        self.submission_repo = submission_repo
        self.document_storage = document_storage
        self.publisher = publisher
        self.consumer = consumer
        self.extractor = extractor
        self.assessor = assessor
        self.translator = translator
        self.extraction_queue_url = extraction_queue_url
        self.screening_queue_url = screening_queue_url
        self.events_queue_url = events_queue_url
        self.max_documents = max_documents

        self.submission_service = SubmissionService(
            applicant_repo=applicant_repo,
            document_repo=document_repo,
            storage=document_storage,
            publisher=publisher,
            event_repo=event_repo,
            extraction_queue_url=extraction_queue_url,
            submission_repo=submission_repo,
            max_documents=max_documents,
        )

        self.extraction_service = ExtractionService(
            document_repo=document_repo,
            extracted_data_repo=extracted_data_repo,
            storage=document_storage,
            extractor=extractor,
            publisher=publisher,
            event_repo=event_repo,
            screening_queue_url=screening_queue_url,
        )

        self.screening_service = ScreeningService(
            applicant_repo=applicant_repo,
            document_repo=document_repo,
            extracted_data_repo=extracted_data_repo,
            report_repo=screening_report_repo,
            assessor=assessor,
            publisher=publisher,
            event_repo=event_repo,
            events_queue_url=events_queue_url,
            submission_repo=submission_repo,
            translator=translator,
        )
