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

    # AWS / LocalStack
    aws_region: str = "eu-west-1"
    aws_endpoint_url: str | None = None
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    sqs_queue_url: str = ""
    sqs_events_queue_url: str = ""
    sqs_property_extraction_queue_url: str = ""
    sqs_property_discovery_queue_url: str = ""

    # Google Maps
    google_maps_api_key: str = ""

    # S3
    s3_bucket_name: str = "property-documents"

    # Reducto
    reducto_api_key: str = ""

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
