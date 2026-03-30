import aioboto3
from supabase import acreate_client

from customers.adapters.email.resend_email_service import ResendEmailService
from customers.adapters.persistence.supabase_invitation_repo import (
    SupabaseInvitationRepository,
)
from customers.adapters.persistence.supabase_membership_repo import (
    SupabaseMembershipRepository,
)
from customers.adapters.persistence.supabase_notification_repo import (
    SupabaseNotificationRepository,
)
from customers.adapters.persistence.supabase_organization_repo import (
    SupabaseOrganizationRepository,
)
from customers.adapters.persistence.supabase_subscription_repo import (
    SupabaseSubscriptionRepository,
)
from customers.adapters.persistence.supabase_portal_user_repo import (
    SupabasePortalUserRepository,
)
from customers.adapters.persistence.supabase_user_repo import SupabaseUserRepository
from shared.config import Settings
from customers.container import Container
from properties.adapters.ai.openai_id_document_extractor import OpenAIIdDocumentExtractor
from properties.adapters.ai.openai_text_document_classifier import (
    OpenAITextDocumentClassifier,
)
from properties.adapters.ai.reducto_document_parser import ReductoDocumentParser
from properties.adapters.ai.reducto_openai_property_extractor import (
    ReductoOpenAIPropertyExtractor,
)
from properties.adapters.persistence.supabase_document_content_repo import (
    SupabaseDocumentContentRepository,
)
from properties.adapters.persistence.supabase_extraction_job_repo import (
    SupabaseExtractionJobRepository,
)
from properties.adapters.persistence.supabase_property_amenity_repo import (
    SupabasePropertyAmenityRepository,
)
from properties.adapters.persistence.supabase_property_repo import (
    SupabasePropertyRepository,
)
from properties.adapters.places.google_places_service import GooglePlacesService
from properties.adapters.queue.sqs_event_bus import SQSEventBus
from properties.adapters.storage.s3_document_storage import S3DocumentStorage
from properties.container import Container as PropertyContainer
from shared.adapters.sqs_event_publisher import SQSDomainEventPublisher

from listings.adapters.database.listing_repository import SqlAlchemyListingRepository
from listings.container import Container as ListingContainer

from screening.adapters.ai.langchain_screening import LangChainScreeningAssessor
from screening.adapters.ai.langchain_translator import LangChainTranslator
from screening.adapters.ai.reducto_extractor import ReductoDocumentExtractor
from screening.adapters.database.repositories import (
    SqlAlchemyApplicantRepository,
    SqlAlchemyDocumentRepository,
    SqlAlchemyEventRepository,
    SqlAlchemyExtractedDataRepository,
    SqlAlchemyIntakeFormRequestRepository,
    SqlAlchemyScreeningReportRepository,
    SqlAlchemySubmissionRepository,
)
from screening.adapters.queue.sqs_publisher import SQSMessageConsumer, SQSMessagePublisher
from screening.application.crypto import (
    load_private_key_from_env,
    load_public_key_from_env,
)
from screening.container import Container as ApplicantScreeningContainer

from bookings.adapters.database.repositories import (
    SqlAlchemyBookingApplicantRepository,
    SqlAlchemyBookingRepository,
    SqlAlchemySlotRepository,
)
from bookings.adapters.notification.log_notifier import LogNotifier
from bookings.container import Container as BookingContainer

from contract_intelligence.adapters.ai.reducto_client import ReductoClient
from contract_intelligence.adapters.ai.section_analysis_client import SectionAnalysisLLMClient
from contract_intelligence.adapters.database.repositories import (
    SqlAlchemyGeneratedContractRepository,
    SqlAlchemySourceDocumentRepository,
    SqlAlchemySourceSectionRepository,
    SqlAlchemyTemplateRepository,
)
from contract_intelligence.adapters.queue.sqs_publisher import (
    SQSMessagePublisher as ContractSQSPublisher,
)
from contract_intelligence.adapters.storage.s3_file_storage import (
    S3FileStorage as ContractS3FileStorage,
)
from contract_intelligence.container import Container as ContractIntelligenceContainer

_container: Container | None = None
_property_container: PropertyContainer | None = None
_screening_container: ApplicantScreeningContainer | None = None
_listing_container: ListingContainer | None = None
_booking_container: BookingContainer | None = None
_contract_intelligence_container: ContractIntelligenceContainer | None = None


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

    session = aioboto3.Session(
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
    )
    domain_event_publisher = SQSDomainEventPublisher(
        session=session,
        queue_url=settings.sqs_domain_events_queue_url,
        endpoint_url=settings.aws_endpoint_url,
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
        domain_event_publisher=domain_event_publisher,
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


async def get_screening_container() -> ApplicantScreeningContainer:
    global _screening_container
    if _screening_container is not None:
        return _screening_container

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

    # Domain event publisher (shared cross-context queue)
    domain_event_publisher = SQSDomainEventPublisher(
        session=boto_session,
        queue_url=settings.sqs_domain_events_queue_url,
        endpoint_url=settings.aws_endpoint_url,
    )

    # AI adapters
    extractor = ReductoDocumentExtractor(api_key=settings.reducto_api_key)
    assessor = LangChainScreeningAssessor(openai_api_key=settings.openai_api_key)
    translator = LangChainTranslator(openai_api_key=settings.openai_api_key)

    _screening_container = ApplicantScreeningContainer(
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
        domain_event_publisher=domain_event_publisher,
        extraction_queue_url=settings.sqs_applicant_extraction_queue_url,
        screening_queue_url=settings.sqs_screening_queue_url,
        max_documents=settings.max_applicant_documents,
    )
    return _screening_container


async def get_booking_container() -> BookingContainer:
    global _booking_container
    if _booking_container is not None:
        return _booking_container

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    settings = Settings()

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    session = session_factory()

    _booking_container = BookingContainer(
        slot_repo=SqlAlchemySlotRepository(session),
        booking_repo=SqlAlchemyBookingRepository(session),
        applicant_repo=SqlAlchemyBookingApplicantRepository(session),
        notifier=LogNotifier(),
        booking_secret=settings.booking_token_secret,
        booking_link_url=settings.booking_link_url,
    )
    return _booking_container


async def get_contract_intelligence_container() -> ContractIntelligenceContainer:
    global _contract_intelligence_container
    if _contract_intelligence_container is not None:
        return _contract_intelligence_container

    import aioboto3
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    settings = Settings()

    # SQLAlchemy async engine + session
    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    session = session_factory()

    # AWS / S3 / SQS
    boto_session = aioboto3.Session(
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
    )

    storage = ContractS3FileStorage(
        session=boto_session,
        bucket_name=settings.contract_s3_bucket_name,
        endpoint_url=settings.aws_endpoint_url,
    )

    publisher = ContractSQSPublisher(
        session=boto_session,
        endpoint_url=settings.aws_endpoint_url,
    )

    # Domain event publisher (shared cross-context queue)
    domain_event_publisher = SQSDomainEventPublisher(
        session=boto_session,
        queue_url=settings.sqs_domain_events_queue_url,
        endpoint_url=settings.aws_endpoint_url,
    )

    # AI adapters
    reducto = ReductoClient(api_key=settings.reducto_api_key)
    llm = SectionAnalysisLLMClient(openai_api_key=settings.openai_api_key)

    # Repositories
    source_document_repo = SqlAlchemySourceDocumentRepository(session)
    source_section_repo = SqlAlchemySourceSectionRepository(session)
    template_repo = SqlAlchemyTemplateRepository(session)
    generated_contract_repo = SqlAlchemyGeneratedContractRepository(session)

    _contract_intelligence_container = ContractIntelligenceContainer(
        source_document_repo=source_document_repo,
        source_section_repo=source_section_repo,
        template_repo=template_repo,
        generated_contract_repo=generated_contract_repo,
        storage=storage,
        reducto=reducto,
        llm=llm,
        publisher=publisher,
        domain_event_publisher=domain_event_publisher,
        sqs_ingestion_queue_url=settings.sqs_contract_ingestion_queue_url,
        sqs_analysis_queue_url=settings.sqs_contract_analysis_queue_url,
        sqs_ingestion_dlq_url=settings.sqs_contract_ingestion_dlq_url,
        sqs_analysis_dlq_url=settings.sqs_contract_analysis_dlq_url,
        reducto_pipeline_id=settings.reducto_pipeline_id,
        s3_bucket_name=settings.contract_s3_bucket_name,
        aws_endpoint_url=settings.aws_endpoint_url,
        heartbeat_interval=settings.contract_heartbeat_interval,
        heartbeat_extension=settings.contract_heartbeat_extension,
    )
    return _contract_intelligence_container
