"""Properties command-queue worker CLI.

- `--queue extraction` consumes PROPERTY_EXTRACTION_REQUESTED.v1 AND
  BATCH_PROPERTY_EXTRACTION_REQUESTED.v1 (one queue, two event types,
  two handlers registered on the router).
- `--queue enrichment` consumes ENRICH_PROPERTY_REQUESTED.v1 — the POI
  auto-discovery workflow (ADR-010 stage 1+2).
- `--retry-job <uuid>` is an ops helper for retrying a specific FAILED job.

Runs the shared `SQSWorker` (ADR-008).
"""

import argparse
import asyncio
from uuid import UUID

import aioboto3
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
from shared.events.adapters.sqs_message_consumer import SQSMessageConsumer
from shared.events.router import EventRouter
from shared.events.types import (
    BATCH_PROPERTY_EXTRACTION_REQUESTED_V1,
    ENRICH_PROPERTY_REQUESTED_V1,
    PROPERTY_EXTRACTION_REQUESTED_V1,
)
from shared.events.worker import SQSWorker

log = structlog.get_logger()


async def _retry_extraction_job(job_id: str) -> None:
    setup_logging(Settings().log_level)
    container = await get_property_container()
    job = await container.retry_extraction_job.execute(job_id=UUID(job_id))
    log.info("extraction_job_retried", job_id=str(job.id), status=job.status.value)


async def _run_extraction_worker() -> None:
    settings = Settings()
    setup_logging(settings.log_level)
    session = aioboto3.Session(
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
    )
    container = await get_property_container()

    router = EventRouter()
    router.on(PROPERTY_EXTRACTION_REQUESTED_V1, handle_property_extraction_requested)
    router.on(
        BATCH_PROPERTY_EXTRACTION_REQUESTED_V1,
        handle_batch_property_extraction_requested,
    )

    consumer = SQSMessageConsumer(
        session=session,
        queue_url=settings.sqs_property_extraction_queue_url,
        endpoint_url=settings.aws_endpoint_url,
    )
    worker = SQSWorker(
        consumer=consumer,
        router=router,
        context=container,
        worker_name="extraction_worker",
        use_heartbeat=True,
        heartbeat_interval=60,
        heartbeat_extension=120,
    )
    await worker.run()


async def _run_enrichment_worker() -> None:
    settings = Settings()
    setup_logging(settings.log_level)
    session = aioboto3.Session(
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
    )
    container = await get_property_container()

    router = EventRouter()
    router.on(ENRICH_PROPERTY_REQUESTED_V1, handle_enrich_property_requested)

    consumer = SQSMessageConsumer(
        session=session,
        queue_url=settings.sqs_property_enrichment_queue_url,
        endpoint_url=settings.aws_endpoint_url,
    )
    worker = SQSWorker(
        consumer=consumer,
        router=router,
        context=container,
        worker_name="property_enrichment_worker",
        use_heartbeat=True,
        heartbeat_interval=60,
        heartbeat_extension=120,
    )
    await worker.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="Property Management SQS Worker")
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
