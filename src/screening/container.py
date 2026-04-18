from screening.application.ports.extractor import DocumentExtractor
from screening.application.ports.screening import ScreeningAssessor
from screening.application.ports.translator import Translator
from screening.application.ports.unit_of_work import ScreeningUnitOfWork
from screening.application.services.extraction import ExtractionService
from screening.application.services.screening import ScreeningService
from screening.application.services.submission import SubmissionService
from shared.events import DomainEventPublisher
from shared.events.ports import CommandPublisher
from shared.ports.document_storage import DocumentStorage


class Container:
    def __init__(
        self,
        uow: ScreeningUnitOfWork,
        document_storage: DocumentStorage,
        command_publisher: CommandPublisher,
        extractor: DocumentExtractor,
        assessor: ScreeningAssessor,
        domain_event_publisher: DomainEventPublisher,
        extraction_queue_url: str,
        screening_queue_url: str,
        max_documents: int = 5,
        translator: Translator | None = None,
    ) -> None:
        self.uow = uow
        self.document_storage = document_storage
        self.command_publisher = command_publisher
        self.extractor = extractor
        self.assessor = assessor
        self.translator = translator
        self.domain_event_publisher = domain_event_publisher
        self.extraction_queue_url = extraction_queue_url
        self.screening_queue_url = screening_queue_url
        self.max_documents = max_documents

        self.submission_service = SubmissionService(
            uow=uow,
            storage=document_storage,
            command_publisher=command_publisher,
            extraction_queue_url=extraction_queue_url,
            max_documents=max_documents,
        )

        self.extraction_service = ExtractionService(
            uow=uow,
            storage=document_storage,
            extractor=extractor,
            command_publisher=command_publisher,
            screening_queue_url=screening_queue_url,
        )

        self.screening_service = ScreeningService(
            uow=uow,
            assessor=assessor,
            domain_event_publisher=domain_event_publisher,
            translator=translator,
        )
