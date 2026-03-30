from contract_intelligence.application.ports.llm import SectionAnalysisLLMPort
from contract_intelligence.application.ports.messaging import MessagePublisherPort
from contract_intelligence.application.ports.reducto import ReductoPort
from contract_intelligence.application.ports.repositories import (
    GeneratedContractRepository,
    SourceDocumentRepository,
    SourceSectionRepository,
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
from shared.events import DomainEventPublisher


class Container:
    def __init__(
        self,
        source_document_repo: SourceDocumentRepository,
        source_section_repo: SourceSectionRepository,
        template_repo: TemplateRepository,
        generated_contract_repo: GeneratedContractRepository,
        storage: FileStoragePort,
        reducto: ReductoPort,
        llm: SectionAnalysisLLMPort,
        publisher: MessagePublisherPort,
        domain_event_publisher: DomainEventPublisher,
        sqs_ingestion_queue_url: str,
        sqs_analysis_queue_url: str,
        sqs_ingestion_dlq_url: str = "",
        sqs_analysis_dlq_url: str = "",
        reducto_pipeline_id: str = "",
        s3_bucket_name: str = "",
        aws_endpoint_url: str | None = None,
        heartbeat_interval: int = 60,
        heartbeat_extension: int = 120,
    ) -> None:
        # Store repos and adapters
        self.source_document_repo = source_document_repo
        self.source_section_repo = source_section_repo
        self.template_repo = template_repo
        self.generated_contract_repo = generated_contract_repo
        self.storage = storage
        self.reducto = reducto
        self.llm = llm
        self.publisher = publisher
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
            repo=source_document_repo,
            storage=storage,
            publisher=publisher,
            sqs_ingestion_queue_url=sqs_ingestion_queue_url,
            s3_bucket_name=s3_bucket_name,
        )
        self.ingestion_service = IngestionService(
            repo=source_document_repo,
            section_repo=source_section_repo,
            storage=storage,
            reducto=reducto,
            publisher=publisher,
            reducto_pipeline_id=reducto_pipeline_id,
            sqs_analysis_queue_url=sqs_analysis_queue_url,
            s3_bucket_name=s3_bucket_name,
            aws_endpoint_url=aws_endpoint_url,
        )
        self.section_analysis_service = SectionAnalysisService(
            doc_repo=source_document_repo,
            section_repo=source_section_repo,
            llm=llm,
        )
        self.review_service = ReviewService(
            repo=source_document_repo,
        )
        self.template_service = TemplateService(
            repo=template_repo,
        )
        self.generated_contract_service = GeneratedContractService(
            repo=generated_contract_repo,
        )
