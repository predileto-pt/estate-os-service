from properties.application.ports.document_classifier import DocumentClassifier
from properties.application.ports.document_data_extractor import DocumentDataExtractor
from properties.application.ports.document_parser import DocumentParser
from properties.application.ports.document_storage import DocumentStorage
from properties.application.ports.places_service import PlacesService
from properties.application.ports.property_extractor import PropertyExtractorService
from properties.application.ports.repositories.document_content_repository import (
    DocumentContentRepository,
)
from properties.application.ports.repositories.extraction_job_repository import (
    ExtractionJobRepository,
)
from properties.application.ports.repositories.property_amenity_repository import (
    PropertyAmenityRepository,
)
from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.application.use_cases.create_property import CreateProperty
from properties.application.use_cases.create_property_owner import CreatePropertyOwner
from properties.application.use_cases.create_property_price import CreatePropertyPrice
from properties.application.use_cases.list_property_prices import ListPropertyPrices
from properties.application.use_cases.extract_property_owner_from_document import (
    ExtractPropertyOwnerFromDocument,
)
from properties.application.use_cases.generate_upload_urls import GenerateUploadUrls
from properties.application.use_cases.get_extraction_job import GetExtractionJob
from properties.application.use_cases.get_property import GetProperty
from properties.application.use_cases.get_property_owner import GetPropertyOwner
from properties.application.use_cases.list_extraction_jobs import ListExtractionJobs
from properties.application.use_cases.list_active_properties import ListActiveProperties
from properties.application.use_cases.list_properties import ListProperties
from properties.application.use_cases.list_property_owners import ListPropertyOwners
from properties.application.use_cases.process_batch_property_extraction import (
    ProcessBatchPropertyExtraction,
)
from properties.application.use_cases.process_property_extraction import (
    ProcessPropertyExtraction,
)
from properties.application.use_cases.publish_property import PublishProperty
from properties.application.use_cases.submit_batch_property_extraction import (
    SubmitBatchPropertyExtraction,
)
from properties.application.use_cases.retry_extraction_job import RetryExtractionJob
from properties.application.use_cases.submit_property_extraction import (
    SubmitPropertyExtraction,
)
from properties.application.use_cases.delete_property import DeleteProperty
from properties.application.use_cases.delete_property_image import DeletePropertyImage
from properties.application.use_cases.generate_image_upload_urls import (
    GenerateImageUploadUrls,
)
from properties.application.use_cases.record_property_image import RecordPropertyImage
from properties.application.use_cases.reorder_property_images import ReorderPropertyImages
from properties.application.use_cases.update_property_address import (
    UpdatePropertyAddress,
)
from properties.application.use_cases.update_property_owner_contact import (
    UpdatePropertyOwnerContact,
)
from properties.application.use_cases.discover_property_amenities import (
    DiscoverPropertyAmenities,
)
from properties.application.use_cases.get_property_amenities import (
    GetPropertyAmenities,
)
from shared.events.ports import CommandPublisher, EventPublisher


class Container:
    def __init__(
        self,
        property_repo: PropertyRepository,
        document_extractor: DocumentDataExtractor,
        document_storage: DocumentStorage | None = None,
        property_extractor: PropertyExtractorService | None = None,
        extraction_job_repo: ExtractionJobRepository | None = None,
        command_publisher: CommandPublisher | None = None,
        extraction_queue_url: str = "",
        document_classifier: DocumentClassifier | None = None,
        document_parser: DocumentParser | None = None,
        document_content_repo: DocumentContentRepository | None = None,
        domain_event_publisher: EventPublisher | None = None,
        places_service: PlacesService | None = None,
        amenity_repo: PropertyAmenityRepository | None = None,
    ) -> None:
        self.property_repo = property_repo
        self.document_extractor = document_extractor
        self.document_storage = document_storage
        self.property_extractor = property_extractor
        self.extraction_job_repo = extraction_job_repo
        self.command_publisher = command_publisher
        self.extraction_queue_url = extraction_queue_url
        self.document_classifier = document_classifier
        self.document_parser = document_parser
        self.document_content_repo = document_content_repo
        self.domain_event_publisher = domain_event_publisher
        self.places_service = places_service
        self.amenity_repo = amenity_repo

        # Existing use cases
        self.create_property = CreateProperty(
            property_repo=property_repo,
            domain_event_publisher=domain_event_publisher,
        )
        self.list_properties = ListProperties(property_repo=property_repo)
        self.list_active_properties = ListActiveProperties(property_repo=property_repo)
        self.get_property = GetProperty(property_repo=property_repo)
        self.create_property_owner = CreatePropertyOwner(
            property_repo=property_repo,
            domain_event_publisher=domain_event_publisher,
        )
        self.extract_property_owner_from_document = (
            ExtractPropertyOwnerFromDocument(
                property_repo=property_repo,
                document_extractor=document_extractor,
                document_parser=document_parser,
                domain_event_publisher=domain_event_publisher,
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
        self.update_property_owner_contact = UpdatePropertyOwnerContact(
            property_repo=property_repo,
            domain_event_publisher=domain_event_publisher,
        )
        self.update_property_address = UpdatePropertyAddress(
            property_repo=property_repo,
            domain_event_publisher=domain_event_publisher,
        )
        self.publish_property = PublishProperty(
            property_repo=property_repo,
            domain_event_publisher=domain_event_publisher,
        )
        self.create_property_price = CreatePropertyPrice(
            property_repo=property_repo,
            domain_event_publisher=domain_event_publisher,
        )
        self.list_property_prices = ListPropertyPrices(
            property_repo=property_repo,
        )
        self.delete_property_image = DeletePropertyImage(
            property_repo=property_repo,
            domain_event_publisher=domain_event_publisher,
        )
        self.reorder_property_images = ReorderPropertyImages(
            property_repo=property_repo,
            domain_event_publisher=domain_event_publisher,
        )

        # Image use cases (require document_storage)
        if document_storage:
            self.generate_image_upload_urls = GenerateImageUploadUrls(
                document_storage=document_storage,
                property_repo=property_repo,
            )
            self.record_property_image = RecordPropertyImage(
                property_repo=property_repo,
                document_storage=document_storage,
                domain_event_publisher=domain_event_publisher,
            )

        # Extraction use cases (require optional dependencies)
        if document_storage:
            self.generate_upload_urls = GenerateUploadUrls(
                document_storage=document_storage,
            )

        if document_storage and extraction_job_repo and command_publisher:
            self.submit_property_extraction = SubmitPropertyExtraction(
                document_storage=document_storage,
                extraction_job_repo=extraction_job_repo,
                command_publisher=command_publisher,
                extraction_queue_url=extraction_queue_url,
            )

        # Property hard delete (requires document_storage to delete S3 images
        # and extraction_job_repo to cascade jobs).
        if document_storage and extraction_job_repo:
            self.delete_property = DeleteProperty(
                property_repo=property_repo,
                extraction_job_repo=extraction_job_repo,
                document_storage=document_storage,
                domain_event_publisher=domain_event_publisher,
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
                domain_event_publisher=domain_event_publisher,
            )

        if document_storage and extraction_job_repo and command_publisher:
            self.submit_batch_property_extraction = SubmitBatchPropertyExtraction(
                document_storage=document_storage,
                extraction_job_repo=extraction_job_repo,
                command_publisher=command_publisher,
                extraction_queue_url=extraction_queue_url,
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
                domain_event_publisher=domain_event_publisher,
            )

        if extraction_job_repo:
            self.get_extraction_job = GetExtractionJob(
                extraction_job_repo=extraction_job_repo,
            )
            self.list_extraction_jobs = ListExtractionJobs(
                extraction_job_repo=extraction_job_repo,
            )

        if extraction_job_repo and command_publisher:
            self.retry_extraction_job = RetryExtractionJob(
                extraction_job_repo=extraction_job_repo,
                command_publisher=command_publisher,
                extraction_queue_url=extraction_queue_url,
            )

        # Discovery use cases
        if amenity_repo:
            self.get_property_amenities = GetPropertyAmenities(
                property_repo=property_repo,
                amenity_repo=amenity_repo,
            )

        if places_service and amenity_repo:
            self.discover_property_amenities = DiscoverPropertyAmenities(
                property_repo=property_repo,
                places_service=places_service,
                amenity_repo=amenity_repo,
            )
