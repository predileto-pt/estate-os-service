"""Listings domain-event worker CLI.

Consumes the `listings-events-queue` — bound (via topic exchange
routing patterns) to seven event types:

- `PROPERTY_CREATED.v1`, `PROPERTY_UPDATED.v1`, `PROPERTY_DELETED.v1`,
  `PROPERTY_PUBLISHED.v1`, `PROPERTY_UNPUBLISHED.v1`
  → `handle_property_event` (projector)
- `PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT.v1`
  → `handle_address_enrichment`
- `PROPERTY_LISTING_UPDATED.v1`
  → `handle_listing_embedding` (spec `2026-05-listing-semantic-search`)
- `PROPERTY_LISTING_DELETED.v1`
  → `handle_listing_deleted`

All handlers are registered on the same router so the shared
`EventBusWorker` dispatches based on `event.event_type`. Each listings-
internal event has its own routing key so handler isolation per
ADR-008: a poisoned LLM call DLX's only the enrichment event, an
embedding failure DLX's only the embedding event, the already-upserted
`property_listings` row stays alive throughout.

Runs the shared `EventBusWorker` (ADR-008).
"""

import asyncio

import aio_pika
import structlog

from listings.adapters.workers.address_enrichment_handler import handle_address_enrichment
from listings.adapters.workers.embedding_handler import (
    handle_listing_deleted,
    handle_listing_embedding,
)
from listings.adapters.workers.property_event_handler import handle_property_event
from shared.config import Settings, setup_logging
from shared.entrypoints.bootstrap import get_listing_container
from shared.events.adapters.rabbitmq_event_publisher import RabbitMQEventPublisher
from shared.events.adapters.rabbitmq_message_consumer import RabbitMQMessageConsumer
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
from shared.events.worker import EventBusWorker

log = structlog.get_logger()


async def _run_events_worker() -> None:
    settings = Settings()
    setup_logging(settings.log_level)
    connection = await aio_pika.connect_robust(settings.rabbitmq_url, heartbeat=30)
    try:
        listings = await get_listing_container()

        # The projector publishes PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT.v1
        # after each successful upsert. Same RabbitMQ connection as the
        # consumer; channel-per-publish isolates errors.
        publisher = RabbitMQEventPublisher(
            connection=connection,
            exchange=settings.rabbitmq_domain_events_exchange,
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

        # Routing-key patterns mirror today's SNS→SQS subscription matrix.
        # `PROPERTY_*.v1` covers the 5 property events; the three
        # `PROPERTY_LISTING_*.v1` events are listed explicitly for clarity
        # even though they'd also match the broader pattern.
        consumer = RabbitMQMessageConsumer(
            connection=connection,
            queue_name="listings-events-queue",
            bindings=[
                (settings.rabbitmq_domain_events_exchange, "PROPERTY_CREATED.v1"),
                (settings.rabbitmq_domain_events_exchange, "PROPERTY_UPDATED.v1"),
                (settings.rabbitmq_domain_events_exchange, "PROPERTY_DELETED.v1"),
                (settings.rabbitmq_domain_events_exchange, "PROPERTY_PUBLISHED.v1"),
                (settings.rabbitmq_domain_events_exchange, "PROPERTY_UNPUBLISHED.v1"),
                (settings.rabbitmq_domain_events_exchange, "PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT.v1"),
                (settings.rabbitmq_domain_events_exchange, "PROPERTY_LISTING_UPDATED.v1"),
                (settings.rabbitmq_domain_events_exchange, "PROPERTY_LISTING_DELETED.v1"),
            ],
            prefetch_count=5,
            dlx=settings.rabbitmq_dlx,
        )
        worker = EventBusWorker(
            consumer=consumer,
            router=router,
            context=context,
            worker_name="listings_events_worker",
            use_heartbeat=False,
        )
        await worker.run()
    finally:
        await connection.close()


def main() -> None:
    asyncio.run(_run_events_worker())


if __name__ == "__main__":
    main()
