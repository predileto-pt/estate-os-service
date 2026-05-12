"""AWS Lambda entrypoint for the listings domain-event projector.

Consumes from the `listings-events` SQS queue (subscribed via SNS fan-out
to the seven PROPERTY_* / PROPERTY_LISTING_* topics — see
`terraform/production/sns.tf`). One SQS record per invocation
(`batch_size = 1` on the event source mapping). Lambda scales by adding
parallel invocations; the function is unreserved (cheap + idempotent).

Mirrors `_run_events_worker` in `src/listings/entrypoints/events_worker.py`
but drops the SQSWorker poll loop in favour of the Lambda runtime. Handler
registrations and context dict shape are identical.
"""

# Secrets bootstrap must run BEFORE any import that touches `shared.config`
# (which instantiates Settings() at module load to wire Logfire — see
# src/shared/events/lambda_bootstrap.py docstring for the full rationale).
from shared.events.lambda_bootstrap import load_secrets_into_env

load_secrets_into_env()

# All subsequent imports are safe — env vars are now populated.
import aioboto3  # noqa: E402

from listings.adapters.workers.address_enrichment_handler import (  # noqa: E402
    handle_address_enrichment,
)
from listings.adapters.workers.embedding_handler import (  # noqa: E402
    handle_listing_deleted,
    handle_listing_embedding,
)
from listings.adapters.workers.property_event_handler import handle_property_event  # noqa: E402
from shared.config import Settings, setup_logging  # noqa: E402
from shared.entrypoints import bootstrap as _bootstrap  # noqa: E402
from shared.events.adapters.sns_event_publisher import SNSEventPublisher  # noqa: E402
from shared.events.lambda_handler import make_handler  # noqa: E402
from shared.events.router import EventRouter  # noqa: E402
from shared.events.types import (  # noqa: E402
    PROPERTY_CREATED_V1,
    PROPERTY_DELETED_V1,
    PROPERTY_LISTING_DELETED_V1,
    PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT_V1,
    PROPERTY_LISTING_UPDATED_V1,
    PROPERTY_PUBLISHED_V1,
    PROPERTY_UNPUBLISHED_V1,
    PROPERTY_UPDATED_V1,
)


def _build_router() -> EventRouter:
    """Register every listings-events handler on a single router.

    Built once per Lambda cold start, reused across warm invocations.
    `EventRouter` is a sync dict — no async resources to leak.
    """
    router = EventRouter()
    router.on(PROPERTY_CREATED_V1, handle_property_event)
    router.on(PROPERTY_UPDATED_V1, handle_property_event)
    router.on(PROPERTY_DELETED_V1, handle_property_event)
    router.on(PROPERTY_PUBLISHED_V1, handle_property_event)
    router.on(PROPERTY_UNPUBLISHED_V1, handle_property_event)
    router.on(PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT_V1, handle_address_enrichment)
    router.on(PROPERTY_LISTING_UPDATED_V1, handle_listing_embedding)
    router.on(PROPERTY_LISTING_DELETED_V1, handle_listing_deleted)
    return router


async def _build_context() -> dict:
    """Fresh per-invocation context — listings container + SNS publisher.

    `shared.entrypoints.bootstrap` caches containers as module-level
    globals. Those containers hold async clients (Supabase, aioboto3
    SNS) bound to whichever event loop created them. Since the Lambda
    handler calls `asyncio.run(...)` per invocation, every warm
    invocation runs under a fresh loop — using a cached container would
    raise "Future attached to a different loop" errors. Invalidate the
    relevant globals to force a clean rebuild.
    """
    _bootstrap._listing_container = None
    _bootstrap._jobs_container = None

    settings = Settings()
    setup_logging(settings.log_level)

    listings = await _bootstrap.get_listing_container()

    session = aioboto3.Session(
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
    )
    publisher = SNSEventPublisher(
        session=session,
        topic_arn_prefix=settings.sns_domain_events_topic_arn_prefix,
        endpoint_url=settings.aws_endpoint_url,
    )

    return {"listings": listings, "publisher": publisher}


# Router is module-level — built once per cold start, reused warm.
_router = _build_router()

# The exported Lambda handler. Configure the function's
# `image_config.command` in terraform to `listings.entrypoints.lambda_events.handler`.
handler = make_handler(_router, _build_context)
