"""Listings domain-event worker CLI.

Consumes the `listings-events-queue` — subscribed (via SNS fan-out) to
seven topics:

- `PROPERTY_CREATED.v1`, `PROPERTY_UPDATED.v1`, `PROPERTY_DELETED.v1`,
  `PROPERTY_PUBLISHED.v1`
  → `handle_property_event` (projector)
- `PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT.v1`
  → `handle_address_enrichment`
- `PROPERTY_LISTING_UPDATED.v1`
  → `handle_listing_embedding` (spec `2026-05-listing-semantic-search`)
- `PROPERTY_LISTING_DELETED.v1`
  → `handle_listing_deleted`

All handlers are registered on the same router so the shared
`SQSWorker` dispatches based on `event.event_type`. Each listings-
internal event lives on its own SNS topic so handler isolation per
ADR-008: a poisoned LLM call DLQs only the enrichment event, an
embedding failure DLQs only the embedding event, the already-upserted
`property_listings` row stays alive throughout.

Runs the shared `SQSWorker` (ADR-008).
"""

import asyncio

import aioboto3
import structlog

from listings.adapters.workers.address_enrichment_handler import handle_address_enrichment
from listings.adapters.workers.embedding_handler import (
    handle_listing_deleted,
    handle_listing_embedding,
)
from listings.adapters.workers.property_event_handler import handle_property_event
from shared.config import Settings, setup_logging
from shared.entrypoints.bootstrap import get_listing_container
from shared.events.adapters.sns_event_publisher import SNSEventPublisher
from shared.events.adapters.sqs_message_consumer import SQSMessageConsumer
from shared.events.router import EventRouter
from shared.events.types import (
    PROPERTY_CREATED_V1,
    PROPERTY_DELETED_V1,
    PROPERTY_LISTING_DELETED_V1,
    PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT_V1,
    PROPERTY_LISTING_UPDATED_V1,
    PROPERTY_PUBLISHED_V1,
    PROPERTY_UNPUBLISHED_V1,
    PROPERTY_UPDATED_V1,
)
from shared.events.worker import SQSWorker

log = structlog.get_logger()


async def _run_events_worker() -> None:
    settings = Settings()
    setup_logging(settings.log_level)
    session = aioboto3.Session(
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
    )

    listings = await get_listing_container()

    # The projector publishes PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT.v1
    # after each successful upsert. Separate SNS topic, same listings
    # queue subscribes — handler isolation for LLM failures.
    publisher = SNSEventPublisher(
        session=session,
        topic_arn_prefix=settings.sns_domain_events_topic_arn_prefix,
        endpoint_url=settings.aws_endpoint_url,
    )

    router = EventRouter()
    router.on(PROPERTY_CREATED_V1, handle_property_event)
    router.on(PROPERTY_UPDATED_V1, handle_property_event)
    router.on(PROPERTY_DELETED_V1, handle_property_event)
    router.on(PROPERTY_PUBLISHED_V1, handle_property_event)
    router.on(PROPERTY_UNPUBLISHED_V1, handle_property_event)
    router.on(PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT_V1, handle_address_enrichment)
    router.on(PROPERTY_LISTING_UPDATED_V1, handle_listing_embedding)
    router.on(PROPERTY_LISTING_DELETED_V1, handle_listing_deleted)

    context = {
        "listings": listings,
        "publisher": publisher,
    }

    consumer = SQSMessageConsumer(
        session=session,
        queue_url=settings.sqs_listings_events_queue_url,
        endpoint_url=settings.aws_endpoint_url,
    )
    worker = SQSWorker(
        consumer=consumer,
        router=router,
        context=context,
        worker_name="listings_events_worker",
        use_heartbeat=True,
        heartbeat_interval=60,
        heartbeat_extension=120,
    )
    await worker.run()


def main() -> None:
    asyncio.run(_run_events_worker())


if __name__ == "__main__":
    main()
