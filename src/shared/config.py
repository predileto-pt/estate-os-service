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

    # AWS / LocalStack
    aws_region: str = "eu-west-1"
    aws_endpoint_url: str | None = None
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    # Domain events (SNS fan-out — ADR-008). The publisher resolves the topic
    # ARN per event type: `${prefix}${event_type.replace('.', '-')}`.
    # Example: `arn:aws:sns:eu-west-1:123:domain-events-PROPERTY_CREATED-v1`.
    sns_domain_events_topic_arn_prefix: str = ""

    # Per-context domain-event SQS queues (each subscribed to the SNS topics
    # it handles). Each has its own DLQ with `maxReceiveCount=5`.
    sqs_customers_events_queue_url: str = ""
    sqs_customers_events_dlq_url: str = ""
    sqs_bookings_events_queue_url: str = ""
    sqs_bookings_events_dlq_url: str = ""
    sqs_properties_events_queue_url: str = ""
    sqs_properties_events_dlq_url: str = ""
    sqs_listings_events_queue_url: str = ""
    sqs_listings_events_dlq_url: str = ""

    # Command queues (point-to-point via `SQSCommandPublisher`). Every queue
    # gets a DLQ with `maxReceiveCount=5`.
    sqs_property_extraction_queue_url: str = ""
    sqs_property_extraction_dlq_url: str = ""
    sqs_property_enrichment_queue_url: str = ""
    sqs_property_enrichment_dlq_url: str = ""
    sqs_applicant_extraction_queue_url: str = ""
    sqs_applicant_extraction_dlq_url: str = ""
    sqs_applicant_screening_queue_url: str = ""
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
    sqs_contract_ingestion_queue_url: str = ""
    sqs_contract_analysis_queue_url: str = ""
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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


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
