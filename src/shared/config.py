import logging

import logfire
import structlog
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "development"
    log_level: str = "info"

    # Supabase
    supabase_url: str = "http://127.0.0.1:54321"
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""

    # Resend
    resend_api_key: str = ""

    # OpenAI
    openai_api_key: str = ""
    # Model used by `LangChainAddressParser` to resolve
    # parish/municipality/district from a property's free-text address.
    # Overridable via env so we can roll forward without a code deploy.
    address_parser_model: str = "gpt-4o-mini"
    # Model for the property description enhancer (LangChain + OpenAI).
    # Overridable per env so we can swap variants without a deploy.
    description_enhancer_model: str = "gpt-4o-mini"

    # Listings semantic-search embedding pipeline (spec
    # `2026-05-listing-semantic-search`, ADR-013). Gate is off by
    # default — flip `listings_embedding_enabled` to wire real adapters
    # at bootstrap time. When the gate is off the listings embedding
    # handler is a no-op so messages are still consumed (no DLQ buildup).
    listings_embedding_enabled: bool = False
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    vector_index_provider: str = "pinecone"
    vector_index_namespace: str = "openai-text-embedding-3-small-v1"
    pinecone_api_key: str = ""
    # Pinecone host (preferred). Skips the control-plane describe call
    # at startup. Format: `<index>-<projectid>.svc.<region>.pinecone.io`
    # — copy from the Pinecone dashboard or `pc index describe`.
    pinecone_host: str = ""
    # Index name. Used as a fallback when `pinecone_host` is empty —
    # the adapter resolves the host lazily on first use via
    # `pc.index(name=...)`. Also useful for ops scripts.
    pinecone_index: str = "listings-prod"
    # Cloud + region. Informational only — used by setup runbooks +
    # operators when provisioning the index. The runtime adapter
    # doesn't read these (the host already encodes the region).
    pinecone_cloud: str = "aws"
    pinecone_region: str = "us-east-1"

    # Listings semantic-search read path (spec
    # `2026-05-listing-semantic-search-read-path`, ADR-013 phase 2).
    # Off by default. When off, the public `?q=…` query param is
    # silently ignored — the route falls through to the existing
    # structured-filter path. When on, the route runs the
    # SearchListings pipeline (rewrite → embed → ANN → hydrate).
    listings_search_enabled: bool = False
    # LLM model for QueryUnderstandingService. `gpt-4o-mini` is the
    # cheap PT-capable default. Bump to a stronger model only after
    # retrieval quality data justifies it.
    search_llm_model: str = "gpt-4o-mini"
    search_llm_timeout_seconds: float = 4.0
    search_llm_max_output_tokens: int = 200
    # Cap on Pinecone `top_k` for the search read path. With the
    # search-result cache (ADR-016 §8), the use case fetches this
    # many ranked IDs ONCE per (q, filters) and slices subsequent
    # pages from the cached list — so the per-page Pinecone fetch
    # goes away. 200 caps search depth at ~10 infinite-scroll pages
    # of 20, which matches observed user behavior ("users only go
    # to page 5" per the spec brainstorm).
    listings_search_ranked_list_size: int = 200

    # Listings page cache (ADR-016).
    redis_url: str = "redis://localhost:6379/0"
    listings_page_cache_enabled: bool = False
    listings_page_cache_ttl_seconds: int = 90
    # ADR-014 hybrid retrieval — SQL pre-filter knobs.
    # `SEARCH_MAX_PRE_FILTER_CANDIDATES`: cap on the SQL pre-filter
    # result. When the result equals this cap, the cardinality guard
    # in SearchListings switches to broad-mode (Pinecone over the
    # whole namespace, then post-intersect with the candidate set).
    search_max_pre_filter_candidates: int = 1000
    # `SEARCH_BROAD_MODE_OVERSHOOT`: multiplier on Pinecone `top_k`
    # in broad mode. We overshoot to survive the post-intersection
    # filter; final response is still capped to `top_k`.
    search_broad_mode_overshoot: int = 4

    # AWS / LocalStack
    aws_region: str = "eu-west-1"
    aws_endpoint_url: str | None = None
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    # RabbitMQ — active event-bus transport (ADR-008 addendum 2026-05-13).
    # `bootstrap.py` imports the RabbitMQ adapters directly; SNS+SQS settings
    # below are kept for the retained-but-unused adapter unit tests.
    rabbitmq_url: str = ""  # e.g. amqp://guest:guest@localhost:5672/
    rabbitmq_domain_events_exchange: str = "domain-events"
    rabbitmq_dlx: str = "domain-events-dlx"

    # Domain events (SNS fan-out — ADR-008, legacy). Kept for SNS+SQS adapter
    # unit tests; no production code path reads it after the RabbitMQ swap.
    sns_domain_events_topic_arn_prefix: str = ""

    # Per-context domain-event SQS queues (each subscribed to the SNS topics
    # it handles). Each has its own DLQ with `maxReceiveCount=5`.
    sqs_customers_events_queue_url: str = ""
    sqs_customers_events_dlq_url: str = ""
    sqs_bookings_events_queue_url: str = ""
    sqs_bookings_events_dlq_url: str = ""
    sqs_listings_events_queue_url: str = ""
    sqs_listings_events_dlq_url: str = ""

    # Command queues (point-to-point via `SQSCommandPublisher`). Every queue
    # gets a DLQ with `maxReceiveCount=5`.
    property_extraction_queue: str = ""
    sqs_property_extraction_dlq_url: str = ""
    property_enrichment_queue: str = ""
    sqs_property_enrichment_dlq_url: str = ""
    applicant_extraction_queue: str = ""
    sqs_applicant_extraction_dlq_url: str = ""
    applicant_screening_queue: str = ""
    sqs_applicant_screening_dlq_url: str = ""

    # Applicant Screening Encryption (RSA + HMAC for NIF)
    encryption_public_key: str = ""
    encryption_private_key: str = ""
    encryption_hmac_key: str = ""

    # Applicant Screening
    max_applicant_documents: int = 5

    # Google Maps
    google_maps_api_key: str = ""

    # S3
    s3_bucket_name: str = "property-documents"

    # Reducto
    reducto_api_key: str = ""

    # Booking Management
    booking_token_secret: str = ""
    booking_link_url: str = "https://portal.predileto.com/book"

    # Contract Intelligence
    contract_ingestion_queue: str = ""
    contract_analysis_queue: str = ""
    sqs_contract_ingestion_dlq_url: str = ""
    sqs_contract_analysis_dlq_url: str = ""
    contract_s3_bucket_name: str = "contract-intelligence-documents"
    contract_heartbeat_interval: int = 60
    contract_heartbeat_extension: int = 120

    # Logfire
    logfire_token: str = ""

    # Langfuse (CallbackHandler reads these env vars automatically)
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = ""

    # Database (direct PostgreSQL for Alembic migrations)
    database_url: str = ""

    # Portal Supabase project (portal users + portal sessions live here —
    # distinct project from admin Supabase). See ADR + spec
    # `2026-05-portal-session-backend` §2.
    supabase_portal_url: str = ""
    supabase_portal_jwt_secret: str = ""
    supabase_portal_audience: str = "authenticated"

    # Portal Postgres (portal Supabase project's DB). Holds `sessions` and,
    # in a follow-up spec, portal `users`. Independent from `database_url`.
    portal_database_url: str = ""

    # Portal session backend (spec `2026-05-portal-session-backend`).
    session_cookie_domain: str = ""  # empty → host-only (local dev)
    session_cookie_secure: bool = True
    session_cookie_max_age_seconds: int = 31_536_000  # 1 year
    session_last_seen_debounce_seconds: int = 60
    session_anonymous_ttl_days: int = 90
    session_prefs_max_bytes: int = 8192
    session_favorites_max: int = 500
    # Comma-separated `version:base64url_key` pairs (versions are plain ints).
    # Example: `1:abc...,2:def...`. Empty in tests; tests inject keys directly.
    session_signing_keys: str = ""
    session_signing_active_key: int = 0  # 0 = unset; production sets via env

    # CORS
    cors_origins: str = "http://localhost:3000,http://localhost:3001"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # Stripe billing
    stripe_api_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_pro_monthly: str = ""
    stripe_price_pro_yearly: str = ""
    stripe_price_enterprise_monthly: str = ""
    stripe_price_enterprise_yearly: str = ""
    stripe_trial_period_days: int = 7

    # Frontend base URL used to build Checkout / Portal redirect targets.
    app_url: str = "http://localhost:4000"

    @property
    def billing_checkout_success_url(self) -> str:
        return f"{self.app_url}/upgrade/success?session_id={{CHECKOUT_SESSION_ID}}"

    @property
    def billing_checkout_cancel_url(self) -> str:
        return f"{self.app_url}/upgrade?checkout=cancelled"

    @property
    def billing_portal_return_url(self) -> str:
        return f"{self.app_url}/dashboard/settings/subscriptions"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        # Tolerate stale env vars from previous schema versions (e.g. when
        # we drop a setting, ops .env files take a beat to catch up).
        "extra": "ignore",
    }


def setup_logging(log_level: str = "info") -> None:
    # Suppress noisy "Failed to detach context" from OTel async context propagation
    # https://github.com/open-telemetry/opentelemetry-python/issues/2606
    logging.getLogger("opentelemetry.context").setLevel(logging.CRITICAL)

    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if settings.logfire_token:
        logfire.configure(
            token=settings.logfire_token,
            service_name="estate-os",
            environment=settings.app_env,
            console=False,
        )
        processors.append(logfire.StructlogProcessor())
        # Global library instrumentation — patches at module level so any
        # subsequent SQLAlchemy engine / httpx client / OpenAI client gets
        # spans. Lives in `setup_logging` so api AND worker processes share
        # the wiring (api calls this at create_app(); worker entrypoints
        # call it before container construction). `instrument_fastapi`
        # stays in `main.py` because it needs the FastAPI app instance.
        logfire.instrument_sqlalchemy()
        logfire.instrument_httpx()
        logfire.instrument_openai()

    processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


settings = Settings()
