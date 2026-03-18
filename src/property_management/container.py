from property_management.application.ports.document_classifier import DocumentClassifier
from property_management.application.ports.document_data_extractor import DocumentDataExtractor
from property_management.application.ports.document_parser import DocumentParser
from property_management.application.ports.document_storage import DocumentStorage
from property_management.application.ports.event_bus import EventBus
from property_management.application.ports.property_extractor import PropertyExtractorService
from property_management.application.ports.repositories.document_content_repository import (
    DocumentContentRepository,
)
from property_management.application.ports.repositories.extraction_job_repository import (
    ExtractionJobRepository,
)
from property_management.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from property_management.application.use_cases.create_property import CreateProperty
from property_management.application.use_cases.create_property_owner import CreatePropertyOwner
from property_management.application.use_cases.create_property_price import CreatePropertyPrice
from property_management.application.use_cases.list_property_prices import ListPropertyPrices
from property_management.application.use_cases.extract_property_owner_from_document import (
    ExtractPropertyOwnerFromDocument,
)
from property_management.application.use_cases.generate_upload_urls import GenerateUploadUrls
from property_management.application.use_cases.get_extraction_job import GetExtractionJob
from property_management.application.use_cases.get_property import GetProperty
from property_management.application.use_cases.get_property_owner import GetPropertyOwner
from property_management.application.use_cases.list_extraction_jobs import ListExtractionJobs
from property_management.application.use_cases.list_properties import ListProperties
from property_management.application.use_cases.list_property_owners import ListPropertyOwners
from property_management.application.use_cases.process_batch_property_extraction import (
    ProcessBatchPropertyExtraction,
)
from property_management.application.use_cases.process_property_extraction import (
    ProcessPropertyExtraction,
)
from property_management.application.use_cases.submit_batch_property_extraction import (
    SubmitBatchPropertyExtraction,
)
from property_management.application.use_cases.retry_extraction_job import RetryExtractionJob
from property_management.application.use_cases.submit_property_extraction import (
    SubmitPropertyExtraction,
)


class Container:
    def __init__(
        self,
        property_repo: PropertyRepository,
        document_extractor: DocumentDataExtractor,
        document_storage: DocumentStorage | None = None,
        property_extractor: PropertyExtractorService | None = None,
        extraction_job_repo: ExtractionJobRepository | None = None,
        event_bus: EventBus | None = None,
        document_classifier: DocumentClassifier | None = None,
        document_parser: DocumentParser | None = None,
        document_content_repo: DocumentContentRepository | None = None,
    ) -> None:
        self.property_repo = property_repo
        self.document_extractor = document_extractor
        self.document_storage = document_storage
        self.property_extractor = property_extractor
        self.extraction_job_repo = extraction_job_repo
        self.event_bus = event_bus
        self.document_classifier = document_classifier
        self.document_parser = document_parser
        self.document_content_repo = document_content_repo

        # Existing use cases
        self.create_property = CreateProperty(property_repo=property_repo)
        self.list_properties = ListProperties(property_repo=property_repo)
        self.get_property = GetProperty(property_repo=property_repo)
        self.create_property_owner = CreatePropertyOwner(
            property_repo=property_repo,
        )
        self.extract_property_owner_from_document = (
            ExtractPropertyOwnerFromDocument(
                property_repo=property_repo,
                document_extractor=document_extractor,
                document_parser=document_parser,
            )
            if document_parser
            else None
        )
        self.list_property_owners = ListPropertyOwners(
            property_repo=property_repo,
        )
        self.get_property_owner = GetPropertyOwner(
            property_repo=property_repo,
        )
        self.create_property_price = CreatePropertyPrice(
            property_repo=property_repo,
        )
        self.list_property_prices = ListPropertyPrices(
            property_repo=property_repo,
        )

        # Extraction use cases (require optional dependencies)
        if document_storage:
            self.generate_upload_urls = GenerateUploadUrls(
                document_storage=document_storage,
            )

        if document_storage and extraction_job_repo and event_bus:
            self.submit_property_extraction = SubmitPropertyExtraction(
                document_storage=document_storage,
                extraction_job_repo=extraction_job_repo,
                event_bus=event_bus,
            )

        if (
            extraction_job_repo
            and document_storage
            and document_parser
            and property_extractor
            and property_repo
        ):
            self.process_property_extraction = ProcessPropertyExtraction(
                extraction_job_repo=extraction_job_repo,
                document_storage=document_storage,
                document_parser=document_parser,
                property_extractor=property_extractor,
                property_repo=property_repo,
            )

        if document_storage and extraction_job_repo and event_bus:
            self.submit_batch_property_extraction = SubmitBatchPropertyExtraction(
                document_storage=document_storage,
                extraction_job_repo=extraction_job_repo,
                event_bus=event_bus,
            )

        if (
            extraction_job_repo
            and document_storage
            and document_parser
            and document_classifier
            and property_extractor
            and property_repo
            and document_content_repo
        ):
            self.process_batch_property_extraction = ProcessBatchPropertyExtraction(
                extraction_job_repo=extraction_job_repo,
                document_storage=document_storage,
                document_parser=document_parser,
                document_classifier=document_classifier,
                property_extractor=property_extractor,
                document_data_extractor=document_extractor,
                property_repo=property_repo,
                document_content_repo=document_content_repo,
            )

        if extraction_job_repo:
            self.get_extraction_job = GetExtractionJob(
                extraction_job_repo=extraction_job_repo,
            )
            self.list_extraction_jobs = ListExtractionJobs(
                extraction_job_repo=extraction_job_repo,
            )

        if extraction_job_repo and event_bus:
            self.retry_extraction_job = RetryExtractionJob(
                extraction_job_repo=extraction_job_repo,
                event_bus=event_bus,
            )
