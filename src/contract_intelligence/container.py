from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from contract_intelligence.adapters.database.unit_of_work import SqlAlchemyContractUnitOfWork
from contract_intelligence.application.ports.llm import SectionAnalysisLLMPort
from contract_intelligence.application.ports.reducto import ReductoPort
from contract_intelligence.application.ports.repositories import (
    GeneratedContractRepository,
    SourceDocumentRepository,
    TemplateRepository,
)
from contract_intelligence.application.ports.storage import FileStoragePort
from contract_intelligence.application.services.generated_contract_service import (
    GeneratedContractService,
)
from contract_intelligence.application.services.ingestion_service import IngestionService
from contract_intelligence.application.services.review_service import ReviewService
from contract_intelligence.application.services.section_analysis_service import (
    SectionAnalysisService,
)
from contract_intelligence.application.services.source_document_service import (
    SourceDocumentService,
)
from contract_intelligence.application.services.template_service import TemplateService
from shared.events.ports import EventPublisher
from shared.events.ports import CommandPublisher


class Container:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        storage: FileStoragePort,
        reducto: ReductoPort,
        llm: SectionAnalysisLLMPort,
        command_publisher: CommandPublisher,
        domain_event_publisher: EventPublisher,
        sqs_ingestion_queue_url: str,
        sqs_analysis_queue_url: str,
        sqs_ingestion_dlq_url: str = "",
        sqs_analysis_dlq_url: str = "",
        s3_bucket_name: str = "",
        aws_endpoint_url: str | None = None,
        heartbeat_interval: int = 60,
        heartbeat_extension: int = 120,
    ) -> None:
        # Unit of Work
        uow = SqlAlchemyContractUnitOfWork(session_factory)

        # Store adapters (still needed for workers / direct access)
        self.storage = storage
        self.reducto = reducto
        self.llm = llm
        self.command_publisher = command_publisher
        self.domain_event_publisher = domain_event_publisher

        # Config
        self.sqs_ingestion_queue_url = sqs_ingestion_queue_url
        self.sqs_analysis_queue_url = sqs_analysis_queue_url
        self.sqs_ingestion_dlq_url = sqs_ingestion_dlq_url
        self.sqs_analysis_dlq_url = sqs_analysis_dlq_url
        self.heartbeat_interval = heartbeat_interval
        self.heartbeat_extension = heartbeat_extension

        # Compose services
        self.source_document_service = SourceDocumentService(
            uow=uow,
            storage=storage,
            command_publisher=command_publisher,
            sqs_ingestion_queue_url=sqs_ingestion_queue_url,
            s3_bucket_name=s3_bucket_name,
        )
        self.ingestion_service = IngestionService(
            uow=uow,
            storage=storage,
            reducto=reducto,
            command_publisher=command_publisher,
            sqs_analysis_queue_url=sqs_analysis_queue_url,
            s3_bucket_name=s3_bucket_name,
            aws_endpoint_url=aws_endpoint_url,
        )
        self.section_analysis_service = SectionAnalysisService(
            uow=uow,
            llm=llm,
        )
        self.review_service = ReviewService(
            repo=self._make_review_repo(session_factory),
        )
        self.template_service = TemplateService(
            repo=self._make_template_repo(session_factory),
        )
        self.generated_contract_service = GeneratedContractService(
            repo=self._make_generated_contract_repo(session_factory),
        )

    # ------------------------------------------------------------------
    # ReviewService, TemplateService, and GeneratedContractService have
    # not yet been migrated to use the UoW.  Until that happens we give
    # them a dedicated session so they keep working unchanged.
    # ------------------------------------------------------------------

    @staticmethod
    def _make_review_repo(
        sf: async_sessionmaker[AsyncSession],
    ) -> SourceDocumentRepository:
        from contract_intelligence.adapters.database.repositories import (
            SqlAlchemySourceDocumentRepository,
        )

        return SqlAlchemySourceDocumentRepository(sf())

    @staticmethod
    def _make_template_repo(
        sf: async_sessionmaker[AsyncSession],
    ) -> TemplateRepository:
        from contract_intelligence.adapters.database.repositories import (
            SqlAlchemyTemplateRepository,
        )

        return SqlAlchemyTemplateRepository(sf())

    @staticmethod
    def _make_generated_contract_repo(
        sf: async_sessionmaker[AsyncSession],
    ) -> GeneratedContractRepository:
        from contract_intelligence.adapters.database.repositories import (
            SqlAlchemyGeneratedContractRepository,
        )

        return SqlAlchemyGeneratedContractRepository(sf())
