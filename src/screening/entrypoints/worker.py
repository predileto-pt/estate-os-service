"""Screening command-queue worker CLI.

Two sub-commands, one SQS queue each:
- `--queue extraction` consumes APPLICANT_EXTRACTION_REQUESTED.v1
- `--queue screening` consumes APPLICANT_SCREENING_REQUESTED.v1

Runs the shared `SQSWorker` (ADR-008) with a single-handler `EventRouter`.
Handler failure semantics: see §Failure semantics in the foundation spec —
handler raises → worker nacks → SQS redelivers up to `maxReceiveCount` →
DLQ.
"""

import argparse
import asyncio

import aioboto3
import structlog

from screening.adapters.workers.extraction_processor import (
    handle_applicant_extraction_requested,
)
from screening.adapters.workers.screening_processor import (
    handle_applicant_screening_requested,
)
from shared.config import Settings, setup_logging
from shared.entrypoints.bootstrap import get_screening_container
from shared.events.adapters.sqs_message_consumer import SQSMessageConsumer
from shared.events.router import EventRouter
from shared.events.types import (
    APPLICANT_EXTRACTION_REQUESTED_V1,
    APPLICANT_SCREENING_REQUESTED_V1,
)
from shared.events.worker import SQSWorker

log = structlog.get_logger()


async def _run_extraction_worker() -> None:
    settings = Settings()
    setup_logging(settings.log_level)
    session = aioboto3.Session(
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
    )
    container = await get_screening_container()

    router = EventRouter()
    router.on(APPLICANT_EXTRACTION_REQUESTED_V1, handle_applicant_extraction_requested)

    consumer = SQSMessageConsumer(
        session=session,
        queue_url=settings.sqs_applicant_extraction_queue_url,
        endpoint_url=settings.aws_endpoint_url,
    )
    worker = SQSWorker(
        consumer=consumer,
        router=router,
        context=container,
        worker_name="applicant_extraction_worker",
        use_heartbeat=True,
        heartbeat_interval=60,
        heartbeat_extension=120,
    )
    await worker.run()


async def _run_screening_worker() -> None:
    settings = Settings()
    setup_logging(settings.log_level)
    session = aioboto3.Session(
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
    )
    container = await get_screening_container()

    router = EventRouter()
    router.on(APPLICANT_SCREENING_REQUESTED_V1, handle_applicant_screening_requested)

    consumer = SQSMessageConsumer(
        session=session,
        queue_url=settings.sqs_applicant_screening_queue_url,
        endpoint_url=settings.aws_endpoint_url,
    )
    worker = SQSWorker(
        consumer=consumer,
        router=router,
        context=container,
        worker_name="screening_worker",
        use_heartbeat=True,
        heartbeat_interval=60,
        heartbeat_extension=120,
    )
    await worker.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="Applicant Screening SQS Worker")
    parser.add_argument("--queue", choices=["extraction", "screening"], required=True)
    args = parser.parse_args()

    if args.queue == "extraction":
        asyncio.run(_run_extraction_worker())
    elif args.queue == "screening":
        asyncio.run(_run_screening_worker())


if __name__ == "__main__":
    main()
