"""Properties command-queue worker CLI.

- `--queue extraction` consumes PROPERTY_EXTRACTION_REQUESTED.v1 AND
  BATCH_PROPERTY_EXTRACTION_REQUESTED.v1 (one queue, two event types,
  two handlers registered on the router).
- `--queue enrichment` consumes ENRICH_PROPERTY_REQUESTED.v1 — the POI
  auto-discovery workflow (ADR-010 stage 1+2).
- `--retry-job <uuid>` is an ops helper for retrying a specific FAILED job.

Runs the shared `EventBusWorker` (ADR-008). Transport is RabbitMQ —
each entrypoint opens ONE `connect_robust` connection per process and
passes it to both the consumer and the bootstrap publishers.
"""

import argparse
import asyncio
from uuid import UUID

import aio_pika
import structlog

from properties.adapters.workers.enrichment_processor import (
    handle_enrich_property_requested,
)
from properties.adapters.workers.extraction_processor import (
    handle_batch_property_extraction_requested,
    handle_property_extraction_requested,
)
from shared.config import Settings, setup_logging
from shared.entrypoints.bootstrap import get_property_container
from shared.events.adapters.rabbitmq_message_consumer import RabbitMQMessageConsumer
from shared.events.router import EventRouter
from shared.events.types import (
    BATCH_PROPERTY_EXTRACTION_REQUESTED_V1,
    ENRICH_PROPERTY_REQUESTED_V1,
    PROPERTY_EXTRACTION_REQUESTED_V1,
)
from shared.events.worker import EventBusWorker

log = structlog.get_logger()


async def _retry_extraction_job(job_id: str) -> None:
    setup_logging(Settings().log_level)
    # Retry-job is a one-shot ops path; it opens its own short-lived
    # connection so the use case can publish a new command if needed.
    settings = Settings()
    connection = await aio_pika.connect_robust(settings.rabbitmq_url, heartbeat=30)
    try:
        container = await get_property_container(connection)
        job = await container.retry_extraction_job.execute(job_id=UUID(job_id))
        log.info("extraction_job_retried", job_id=str(job.id), status=job.status.value)
    finally:
        await connection.close()


async def _run_extraction_worker() -> None:
    settings = Settings()
    setup_logging(settings.log_level)
    connection = await aio_pika.connect_robust(settings.rabbitmq_url, heartbeat=30)
    try:
        container = await get_property_container(connection)

        router = EventRouter()
        router.on(PROPERTY_EXTRACTION_REQUESTED_V1, handle_property_extraction_requested)
        router.on(
            BATCH_PROPERTY_EXTRACTION_REQUESTED_V1,
            handle_batch_property_extraction_requested,
        )

        consumer = RabbitMQMessageConsumer(
            connection=connection,
            queue_name="property-extraction-queue",
            bindings=[],  # command queue — no topic-exchange bindings
            prefetch_count=5,
            dlx=settings.rabbitmq_dlx,
        )
        worker = EventBusWorker(
            consumer=consumer,
            router=router,
            context=container,
            worker_name="extraction_worker",
            # RabbitMQ has no per-message visibility timeout —
            # `extend_visibility` is a no-op so we skip the heartbeat task.
            use_heartbeat=False,
        )
        await worker.run()
    finally:
        # Connection close happens AFTER worker.run() returns (after drain).
        # Handlers may publish follow-up events during drain — the publisher
        # rides this same connection.
        await connection.close()


async def _run_enrichment_worker() -> None:
    settings = Settings()
    setup_logging(settings.log_level)
    connection = await aio_pika.connect_robust(settings.rabbitmq_url, heartbeat=30)
    try:
        container = await get_property_container(connection)

        router = EventRouter()
        router.on(ENRICH_PROPERTY_REQUESTED_V1, handle_enrich_property_requested)

        consumer = RabbitMQMessageConsumer(
            connection=connection,
            queue_name="property-enrichment-queue",
            bindings=[],
            prefetch_count=5,
            dlx=settings.rabbitmq_dlx,
        )
        worker = EventBusWorker(
            consumer=consumer,
            router=router,
            context=container,
            worker_name="property_enrichment_worker",
            use_heartbeat=False,
        )
        await worker.run()
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Property Management Worker")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--queue", choices=["extraction", "enrichment"])
    group.add_argument("--retry-job", metavar="JOB_ID", help="Retry a failed extraction job")
    args = parser.parse_args()

    if args.retry_job:
        asyncio.run(_retry_extraction_job(args.retry_job))
    elif args.queue == "extraction":
        asyncio.run(_run_extraction_worker())
    elif args.queue == "enrichment":
        asyncio.run(_run_enrichment_worker())


if __name__ == "__main__":
    main()
