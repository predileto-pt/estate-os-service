import aioboto3
from supabase import acreate_client

from organizations.adapters.email.resend_email_service import ResendEmailService
from organizations.adapters.persistence.supabase_invitation_repo import (
    SupabaseInvitationRepository,
)
from organizations.adapters.persistence.supabase_membership_repo import (
    SupabaseMembershipRepository,
)
from organizations.adapters.persistence.supabase_notification_repo import (
    SupabaseNotificationRepository,
)
from organizations.adapters.persistence.supabase_organization_repo import (
    SupabaseOrganizationRepository,
)
from organizations.adapters.persistence.supabase_subscription_repo import (
    SupabaseSubscriptionRepository,
)
from organizations.adapters.persistence.supabase_user_repo import (
    SupabaseUserRepository as _OrgSupabaseUserRepository,
)
from identity.adapters.persistence.supabase_user_repo import SupabaseUserRepository
from identity.container import Container as IdentityContainer
from shared.config import Settings
from organizations.container import Container
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
from properties.adapters.storage.s3_document_storage import S3DocumentStorage
from properties.container import Container as PropertyContainer
from shared.events.adapters.sns_event_publisher import SNSEventPublisher
from shared.events.adapters.sqs_command_publisher import SQSCommandPublisher

from listings.adapters.database.listing_repository import SqlAlchemyListingRepository
from listings.container import Container as ListingContainer

from screening.adapters.ai.langchain_screening import LangChainScreeningAssessor
from screening.adapters.ai.langchain_translator import LangChainTranslator
from screening.adapters.ai.reducto_extractor import ReductoDocumentExtractor
from screening.adapters.database.unit_of_work import SqlAlchemyScreeningUnitOfWork
from screening.application.crypto import (
    load_private_key_from_env,
    load_public_key_from_env,
)
from screening.container import Container as ApplicantScreeningContainer

from bookings.adapters.database.unit_of_work import SqlAlchemyBookingUnitOfWork
from bookings.adapters.notification.log_notifier import LogNotifier
from bookings.container import Container as BookingContainer

from contract_intelligence.adapters.ai.reducto_client import ReductoClient
from contract_intelligence.adapters.ai.section_analysis_client import SectionAnalysisLLMClient
from contract_intelligence.adapters.storage.s3_file_storage import (
    S3FileStorage as ContractS3FileStorage,
)
from contract_intelligence.container import Container as ContractIntelligenceContainer

_container: Container | None = None
_identity_container: IdentityContainer | None = None
_property_container: PropertyContainer | None = None
_screening_container: ApplicantScreeningContainer | None = None
_listing_container: ListingContainer | None = None
_booking_container: BookingContainer | None = None
_contract_intelligence_container: ContractIntelligenceContainer | None = None


async def get_identity_container() -> IdentityContainer:
    """Identity context container.

    Wires the identity `User` aggregate over the `SupabaseUserRepository`
    adapter (prod). Exposes `register_user_port` and `user_lookup_by_id`
    callable bindings for cross-context injection into the organizations
    container.
    """
    global _identity_container
    if _identity_container is not None:
        return _identity_container

    settings = Settings()
    client = await acreate_client(settings.supabase_url, settings.supabase_service_role_key)
    _identity_container = IdentityContainer(user_repo=SupabaseUserRepository(client))
    return _identity_container


async def get_container() -> Container:
    """Organizations context container.

    Keeps its own `UserRepository` adapter over the `users` table — the
    org-side `User` is an internal mirror of `identity.User` used by
    membership/invitation use cases that look up users by email/id. This
    keeps the `grep "from identity" src/organizations/` acceptance
    criterion tight (no identity.domain imports leaking into org
    business code). `PortalUser` is gone (collapsed into `User`).
    """
    global _container
    if _container is not None:
        return _container

    settings = Settings()
    client = await acreate_client(settings.supabase_url, settings.supabase_service_role_key)

    # Identity container must be built first — organizations depends on
    # its `register_user_port` callable binding.
    identity = await get_identity_container()

    _container = Container(
        user_repo=_OrgSupabaseUserRepository(client),
        organization_repo=SupabaseOrganizationRepository(client),
        subscription_repo=SupabaseSubscriptionRepository(client),
        notification_repo=SupabaseNotificationRepository(client),
        membership_repo=SupabaseMembershipRepository(client),
        invitation_repo=SupabaseInvitationRepository(client),
        email_service=ResendEmailService(settings.resend_api_key),
        register_user_port=identity.register_user_port,
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

    document_classifier = OpenAITextDocumentClassifier(settings.openai_api_key)
    document_data_extractor = OpenAIIdDocumentExtractor(settings.openai_api_key)

    session = aioboto3.Session(
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
    )
    # Shared command publisher + domain-event publisher. Properties' legacy
    # per-context SQSEventBus is gone (ADR-008); extraction commands go out
    # via the canonical envelope on the same shared SQSCommandPublisher every
    # other context uses.
    command_publisher = SQSCommandPublisher(
        session=session,
        endpoint_url=settings.aws_endpoint_url,
    )
    domain_event_publisher = SNSEventPublisher(
        session=session,
        topic_arn_prefix=settings.sns_domain_events_topic_arn_prefix,
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
        command_publisher=command_publisher,
        extraction_queue_url=settings.sqs_property_extraction_queue_url,
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

    from listings.adapters.ai.langchain_address_parser import LangChainAddressParser
    from listings.adapters.database.property_listing_repository import (
        SqlAlchemyPropertyListingRepository,
    )

    settings = Settings()
    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    session = session_factory()

    address_parser = LangChainAddressParser(
        model=settings.address_parser_model,
        openai_api_key=settings.openai_api_key,
    )

    _listing_container = ListingContainer(
        listing_repo=SqlAlchemyListingRepository(session),
        property_listing_repo=SqlAlchemyPropertyListingRepository(session),
        address_parser=address_parser,
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

    # SQLAlchemy async engine + session factory
    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Encryption keys
    public_key = load_public_key_from_env(settings.encryption_public_key)
    private_key = load_private_key_from_env(settings.encryption_private_key)
    hmac_key = base64.b64decode(settings.encryption_hmac_key)

    # Unit of Work
    uow = SqlAlchemyScreeningUnitOfWork(session_factory, public_key, private_key, hmac_key)

    # S3
    document_storage = S3DocumentStorage(
        bucket_name=settings.s3_bucket_name,
        region=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )

    # SQS — shared command publisher; sends canonical DomainEvent envelopes.
    boto_session = aioboto3.Session()
    command_publisher = SQSCommandPublisher(
        session=boto_session, endpoint_url=settings.aws_endpoint_url
    )

    # Domain event publisher (SNS fan-out — ADR-008).
    domain_event_publisher = SNSEventPublisher(
        session=boto_session,
        topic_arn_prefix=settings.sns_domain_events_topic_arn_prefix,
        endpoint_url=settings.aws_endpoint_url,
    )

    # AI adapters
    extractor = ReductoDocumentExtractor(api_key=settings.reducto_api_key)
    assessor = LangChainScreeningAssessor(openai_api_key=settings.openai_api_key)
    translator = LangChainTranslator(openai_api_key=settings.openai_api_key)

    _screening_container = ApplicantScreeningContainer(
        uow=uow,
        document_storage=document_storage,
        command_publisher=command_publisher,
        extractor=extractor,
        assessor=assessor,
        translator=translator,
        domain_event_publisher=domain_event_publisher,
        extraction_queue_url=settings.sqs_applicant_extraction_queue_url,
        screening_queue_url=settings.sqs_applicant_screening_queue_url,
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

    uow = SqlAlchemyBookingUnitOfWork(session_factory)

    _booking_container = BookingContainer(
        uow=uow,
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

    # SQLAlchemy async engine + session factory
    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

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

    command_publisher = SQSCommandPublisher(
        session=boto_session,
        endpoint_url=settings.aws_endpoint_url,
    )

    # Domain event publisher (SNS fan-out — ADR-008).
    domain_event_publisher = SNSEventPublisher(
        session=boto_session,
        topic_arn_prefix=settings.sns_domain_events_topic_arn_prefix,
        endpoint_url=settings.aws_endpoint_url,
    )

    # AI adapters
    reducto = ReductoClient(api_key=settings.reducto_api_key)
    llm = SectionAnalysisLLMClient(openai_api_key=settings.openai_api_key)

    _contract_intelligence_container = ContractIntelligenceContainer(
        session_factory=session_factory,
        storage=storage,
        reducto=reducto,
        llm=llm,
        command_publisher=command_publisher,
        domain_event_publisher=domain_event_publisher,
        sqs_ingestion_queue_url=settings.sqs_contract_ingestion_queue_url,
        sqs_analysis_queue_url=settings.sqs_contract_analysis_queue_url,
        sqs_ingestion_dlq_url=settings.sqs_contract_ingestion_dlq_url,
        sqs_analysis_dlq_url=settings.sqs_contract_analysis_dlq_url,
        s3_bucket_name=settings.contract_s3_bucket_name,
        aws_endpoint_url=settings.aws_endpoint_url,
        heartbeat_interval=settings.contract_heartbeat_interval,
        heartbeat_extension=settings.contract_heartbeat_extension,
    )
    return _contract_intelligence_container
