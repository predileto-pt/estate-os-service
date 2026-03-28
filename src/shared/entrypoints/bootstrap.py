from supabase import acreate_client

from customer_management.adapters.email.resend_email_service import ResendEmailService
from customer_management.adapters.inmemory.inmemory_event_bus import InMemoryEventBus
from customer_management.adapters.persistence.supabase_invitation_repo import (
    SupabaseInvitationRepository,
)
from customer_management.adapters.persistence.supabase_membership_repo import (
    SupabaseMembershipRepository,
)
from customer_management.adapters.persistence.supabase_notification_repo import (
    SupabaseNotificationRepository,
)
from customer_management.adapters.persistence.supabase_organization_repo import (
    SupabaseOrganizationRepository,
)
from customer_management.adapters.persistence.supabase_subscription_repo import (
    SupabaseSubscriptionRepository,
)
from customer_management.adapters.persistence.supabase_portal_user_repo import (
    SupabasePortalUserRepository,
)
from customer_management.adapters.persistence.supabase_user_repo import SupabaseUserRepository
from shared.config import Settings
from customer_management.container import Container
from property_management.adapters.ai.openai_id_document_extractor import OpenAIIdDocumentExtractor
from property_management.adapters.ai.openai_text_document_classifier import (
    OpenAITextDocumentClassifier,
)
from property_management.adapters.ai.reducto_document_parser import ReductoDocumentParser
from property_management.adapters.ai.reducto_openai_property_extractor import (
    ReductoOpenAIPropertyExtractor,
)
from property_management.adapters.persistence.supabase_document_content_repo import (
    SupabaseDocumentContentRepository,
)
from property_management.adapters.persistence.supabase_extraction_job_repo import (
    SupabaseExtractionJobRepository,
)
from property_management.adapters.persistence.supabase_property_amenity_repo import (
    SupabasePropertyAmenityRepository,
)
from property_management.adapters.persistence.supabase_property_repo import (
    SupabasePropertyRepository,
)
from property_management.adapters.places.google_places_service import GooglePlacesService
from property_management.adapters.queue.sqs_event_bus import SQSEventBus
from property_management.adapters.storage.s3_document_storage import S3DocumentStorage
from property_management.container import Container as PropertyContainer

from properties_listing.adapters.database.listing_repository import SqlAlchemyListingRepository
from properties_listing.container import Container as ListingContainer

from applicant_screening.adapters.ai.langchain_screening import LangChainScreeningAssessor
from applicant_screening.adapters.ai.langchain_translator import LangChainTranslator
from applicant_screening.adapters.ai.reducto_extractor import ReductoDocumentExtractor
from applicant_screening.adapters.database.repositories import (
    SqlAlchemyApplicantRepository,
    SqlAlchemyDocumentRepository,
    SqlAlchemyEventRepository,
    SqlAlchemyExtractedDataRepository,
    SqlAlchemyIntakeFormRequestRepository,
    SqlAlchemyScreeningReportRepository,
    SqlAlchemySubmissionRepository,
)
from applicant_screening.adapters.queue.sqs_publisher import SQSMessageConsumer, SQSMessagePublisher
from applicant_screening.application.crypto import load_private_key_from_env, load_public_key_from_env
from applicant_screening.container import Container as ApplicantScreeningContainer

_container: Container | None = None
_property_container: PropertyContainer | None = None
_applicant_screening_container: ApplicantScreeningContainer | None = None
_listing_container: ListingContainer | None = None


async def get_container() -> Container:
    global _container
    if _container is not None:
        return _container

    settings = Settings()
    client = await acreate_client(settings.supabase_url, settings.supabase_service_role_key)

    _container = Container(
        user_repo=SupabaseUserRepository(client),
        organization_repo=SupabaseOrganizationRepository(client),
        subscription_repo=SupabaseSubscriptionRepository(client),
        notification_repo=SupabaseNotificationRepository(client),
        membership_repo=SupabaseMembershipRepository(client),
        invitation_repo=SupabaseInvitationRepository(client),
        portal_user_repo=SupabasePortalUserRepository(client),
        email_service=ResendEmailService(settings.resend_api_key),
        event_bus=InMemoryEventBus(),
    )
    return _container


async def get_property_container() -> PropertyContainer:
    global _property_container
    if _property_container is not None:
        return _property_container

    settings = Settings()
    client = await acreate_client(settings.supabase_url, settings.supabase_service_role_key)

    document_storage = S3DocumentStorage(
        bucket_name=settings.s3_bucket_name,
        region=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )

    document_parser = ReductoDocumentParser(
        reducto_api_key=settings.reducto_api_key,
    )

    property_extractor = ReductoOpenAIPropertyExtractor(
        openai_api_key=settings.openai_api_key,
    )

    event_bus = SQSEventBus(
        queue_url=settings.sqs_property_extraction_queue_url,
        region=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )

    document_classifier = OpenAITextDocumentClassifier(settings.openai_api_key)
    document_data_extractor = OpenAIIdDocumentExtractor(settings.openai_api_key)

    discovery_event_bus = SQSEventBus(
        queue_url=settings.sqs_property_discovery_queue_url,
        region=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )

    places_service = GooglePlacesService(api_key=settings.google_maps_api_key)
    amenity_repo = SupabasePropertyAmenityRepository(client)

    _property_container = PropertyContainer(
        property_repo=SupabasePropertyRepository(client),
        document_extractor=document_data_extractor,
        document_storage=document_storage,
        property_extractor=property_extractor,
        extraction_job_repo=SupabaseExtractionJobRepository(client),
        event_bus=event_bus,
        document_classifier=document_classifier,
        document_parser=document_parser,
        document_content_repo=SupabaseDocumentContentRepository(client),
        discovery_event_bus=discovery_event_bus,
        places_service=places_service,
        amenity_repo=amenity_repo,
    )
    return _property_container


async def get_listing_container() -> ListingContainer:
    global _listing_container
    if _listing_container is not None:
        return _listing_container

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    settings = Settings()
    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    session = session_factory()

    _listing_container = ListingContainer(
        listing_repo=SqlAlchemyListingRepository(session),
    )
    return _listing_container


async def get_applicant_screening_container() -> ApplicantScreeningContainer:
    global _applicant_screening_container
    if _applicant_screening_container is not None:
        return _applicant_screening_container

    import base64

    import aioboto3
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    settings = Settings()

    # SQLAlchemy async engine + session
    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    session = session_factory()

    # Encryption keys
    public_key = load_public_key_from_env(settings.encryption_public_key)
    private_key = load_private_key_from_env(settings.encryption_private_key)
    hmac_key = base64.b64decode(settings.encryption_hmac_key)

    # S3
    document_storage = S3DocumentStorage(
        bucket_name=settings.s3_bucket_name,
        region=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )

    # SQS
    boto_session = aioboto3.Session()
    publisher = SQSMessagePublisher(boto_session, endpoint_url=settings.aws_endpoint_url)
    consumer = SQSMessageConsumer(boto_session, endpoint_url=settings.aws_endpoint_url)

    # AI adapters
    extractor = ReductoDocumentExtractor(api_key=settings.reducto_api_key)
    assessor = LangChainScreeningAssessor(openai_api_key=settings.openai_api_key)
    translator = LangChainTranslator(openai_api_key=settings.openai_api_key)

    _applicant_screening_container = ApplicantScreeningContainer(
        applicant_repo=SqlAlchemyApplicantRepository(session, public_key, private_key, hmac_key),
        document_repo=SqlAlchemyDocumentRepository(session),
        extracted_data_repo=SqlAlchemyExtractedDataRepository(session),
        screening_report_repo=SqlAlchemyScreeningReportRepository(session),
        event_repo=SqlAlchemyEventRepository(session),
        intake_form_request_repo=SqlAlchemyIntakeFormRequestRepository(session),
        submission_repo=SqlAlchemySubmissionRepository(session),
        document_storage=document_storage,
        publisher=publisher,
        consumer=consumer,
        extractor=extractor,
        assessor=assessor,
        translator=translator,
        extraction_queue_url=settings.sqs_applicant_extraction_queue_url,
        screening_queue_url=settings.sqs_applicant_screening_queue_url,
        events_queue_url=settings.sqs_events_queue_url,
        max_documents=settings.max_applicant_documents,
    )
    return _applicant_screening_container
