import aioboto3
from supabase import acreate_client

from billing.adapters.outbound.stripe.billing_gateway import StripeBillingGateway
from billing.adapters.persistence.supabase_stripe_webhook_events_repo import (
    SupabaseStripeWebhookEventsRepository,
)
from billing.adapters.persistence.supabase_subscription_repo import (
    SupabaseSubscriptionRepository,
)
from billing.application.use_cases.price_catalog import PriceCatalog
from billing.container import Container as BillingContainer
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
from properties.adapters.persistence.supabase_property_poi_repo import (
    SupabasePropertyPoiRepository,
)
from properties.adapters.persistence.supabase_property_repo import (
    SupabasePropertyRepository,
)
from properties.adapters.places.google_places_service import GooglePlacesService
from properties.adapters.storage.s3_document_storage import S3DocumentStorage
from properties.container import Container as PropertyContainer
from shared.events.adapters.sns_event_publisher import SNSEventPublisher
from shared.events.adapters.sqs_command_publisher import SQSCommandPublisher
from shared.jobs.adapters.persistence.supabase_job_repository import (
    SupabaseJobRepository,
)
from shared.jobs.container import SharedJobsContainer

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
_billing_container: BillingContainer | None = None
_property_container: PropertyContainer | None = None
_screening_container: ApplicantScreeningContainer | None = None
_listing_container: ListingContainer | None = None
_booking_container: BookingContainer | None = None
_contract_intelligence_container: ContractIntelligenceContainer | None = None
_jobs_container: SharedJobsContainer | None = None


async def get_jobs_container() -> SharedJobsContainer:
    """Shared `jobs` infrastructure container (ADR-012).

    Owns one Supabase-backed `JobRepository` and exposes the `JobTracker`
    write port other contexts inject + the read use cases (ListJobs,
    GetJob) the `/admin/jobs` routes call.
    """
    global _jobs_container
    if _jobs_container is not None:
        return _jobs_container
    settings = Settings()
    client = await acreate_client(settings.supabase_url, settings.supabase_service_role_key)
    _jobs_container = SharedJobsContainer(job_repo=SupabaseJobRepository(client))
    return _jobs_container


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


async def get_billing_container() -> BillingContainer:
    """Billing context container.

    Wires the Subscription aggregate + Stripe integration (Checkout, Portal,
    webhooks, price catalog). Exposes `seed_freemium_subscription_port`
    callable binding for cross-context injection into organizations.
    """
    global _billing_container
    if _billing_container is not None:
        return _billing_container

    settings = Settings()
    client = await acreate_client(settings.supabase_url, settings.supabase_service_role_key)

    billing_gateway = StripeBillingGateway(
        api_key=settings.stripe_api_key,
        webhook_secret=settings.stripe_webhook_secret,
    )
    price_catalog = PriceCatalog(
        pro_monthly=settings.stripe_price_pro_monthly,
        pro_yearly=settings.stripe_price_pro_yearly,
        enterprise_monthly=settings.stripe_price_enterprise_monthly,
        enterprise_yearly=settings.stripe_price_enterprise_yearly,
    )
    # Webhook events: Supabase-backed idempotency + audit log. Each
    # event's full decoded envelope is persisted to `stripe_webhook_events.payload`
    # for debugging and audit. Duplicates on `event_id` are no-ops
    # (`upsert(..., ignore_duplicates=True)`).
    stripe_webhook_events_repo = SupabaseStripeWebhookEventsRepository(client)

    _billing_container = BillingContainer(
        subscription_repo=SupabaseSubscriptionRepository(client),
        billing_gateway=billing_gateway,
        stripe_webhook_events_repo=stripe_webhook_events_repo,
        price_catalog=price_catalog,
        trial_period_days=settings.stripe_trial_period_days,
        checkout_success_url=settings.billing_checkout_success_url,
        checkout_cancel_url=settings.billing_checkout_cancel_url,
        portal_return_url=settings.billing_portal_return_url,
    )
    return _billing_container


async def get_container() -> Container:
    """Organizations context container.

    Keeps its own `UserRepository` adapter over the `users` table — the
    org-side `User` is an internal mirror of `identity.User` used by
    membership/invitation use cases that look up users by email/id. This
    keeps the `grep "from identity" src/organizations/` acceptance
    criterion tight (no identity.domain imports leaking into org
    business code). `PortalUser` is gone (collapsed into `User`).

    Consumes two callable Protocols from sibling contexts:
    - `identity.register_user_port` for RegisterAdminAccount step 1.
    - `billing.seed_freemium_subscription_port` for seeding the default
      freemium Subscription when a fresh org is created.
    """
    global _container
    if _container is not None:
        return _container

    settings = Settings()
    client = await acreate_client(settings.supabase_url, settings.supabase_service_role_key)

    # Identity + billing must be built first — organizations consumes
    # their callable-Protocol bindings.
    identity = await get_identity_container()
    billing = await get_billing_container()

    _container = Container(
        user_repo=_OrgSupabaseUserRepository(client),
        organization_repo=SupabaseOrganizationRepository(client),
        notification_repo=SupabaseNotificationRepository(client),
        membership_repo=SupabaseMembershipRepository(client),
        invitation_repo=SupabaseInvitationRepository(client),
        email_service=ResendEmailService(settings.resend_api_key),
        register_user_port=identity.register_user_port,
        seed_freemium_subscription=billing.seed_freemium_subscription_port,
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
    property_poi_repo = SupabasePropertyPoiRepository(client)

    # Locality sanitizer — drops Google results that fall outside the
    # property's concelho (PT) / city (BR/US/etc) before they're
    # persisted. Skipped when no OpenAI key is configured so dev /
    # CI without a key keeps working.
    poi_locality_filter = None
    if settings.openai_api_key:
        from properties.adapters.ai.openai_poi_locality_filter import (
            OpenAiPoiLocalityFilter,
        )

        poi_locality_filter = OpenAiPoiLocalityFilter(
            openai_api_key=settings.openai_api_key,
        )

    # Shared jobs infra is built first so its tracker can be injected.
    jobs = await get_jobs_container()

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
        property_poi_repo=property_poi_repo,
        enrichment_queue_url=settings.sqs_property_enrichment_queue_url,
        job_tracker=jobs.job_tracker,
        poi_locality_filter=poi_locality_filter,
    )
    return _property_container


async def get_listing_container() -> ListingContainer:
    global _listing_container
    if _listing_container is not None:
        return _listing_container

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from listings.adapters.ai.portugal_address_searcher import PortugalAddressSearcher
    from listings.adapters.database.property_listing_repository import (
        SqlAlchemyPropertyListingRepository,
    )

    settings = Settings()
    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    portugal_address_searcher = PortugalAddressSearcher(
        model=settings.address_parser_model,
        openai_api_key=settings.openai_api_key,
    )

    # Embedding pipeline (spec `2026-05-listing-semantic-search`).
    # Both adapters are constructed only when the gate is on so a
    # misconfigured prod (missing PINECONE_API_KEY) doesn't crash the
    # worker — instead the embedding handler short-circuits to a
    # no-op until ops flips the gate.
    embedding_provider = None
    vector_index = None
    if settings.listings_embedding_enabled:
        from listings.adapters.embedding.openai_provider import OpenAIEmbeddingProvider
        from listings.adapters.vector.pinecone_index import PineconeVectorIndex

        embedding_provider = OpenAIEmbeddingProvider(
            api_key=settings.openai_api_key,
            model=settings.embedding_model,
        )
        # Prefer host (skips the describe RTT); fall back to name.
        vector_index = PineconeVectorIndex(
            api_key=settings.pinecone_api_key,
            host=settings.pinecone_host or None,
            index_name=settings.pinecone_index or None,
        )

    # Search read path (spec
    # `2026-05-listing-semantic-search-read-path`, ADR-013 phase 2).
    # Always wire a QueryUnderstandingService — when the gate is off
    # we use the identity adapter so the container never has None
    # there and the route never branches on adapter presence.
    if settings.listings_search_enabled:
        from listings.adapters.ai.langchain_query_extractor import (
            LangChainQueryExtractor,
        )

        query_extractor = LangChainQueryExtractor(
            model=settings.search_llm_model,
            openai_api_key=settings.openai_api_key,
            timeout_seconds=settings.search_llm_timeout_seconds,
            max_output_tokens=settings.search_llm_max_output_tokens,
        )
    else:
        from listings.adapters.inmemory.inmemory_query_extractor import (
            IdentityQueryExtractor,
        )

        query_extractor = IdentityQueryExtractor()

    _listing_container = ListingContainer(
        property_listing_repo=SqlAlchemyPropertyListingRepository(session_factory),
        portugal_address_searcher=portugal_address_searcher,
        embedding_provider=embedding_provider,
        vector_index=vector_index,
        vector_index_namespace=settings.vector_index_namespace,
        embedding_model_version=settings.embedding_model,
        query_extractor=query_extractor,
        vector_index_top_k=settings.vector_index_top_k,
        max_pre_filter_candidates=settings.search_max_pre_filter_candidates,
        broad_mode_overshoot=settings.search_broad_mode_overshoot,
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
