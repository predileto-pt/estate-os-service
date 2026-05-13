"""Screening command-queue worker CLI.

Two sub-commands, one queue each:
- `--queue extraction` consumes APPLICANT_EXTRACTION_REQUESTED.v1
- `--queue screening` consumes APPLICANT_SCREENING_REQUESTED.v1

Runs the shared `EventBusWorker` (ADR-008) with a single-handler `EventRouter`.
Handler failure semantics: handler raises → worker nacks → broker requeues
up to `x-delivery-limit=5` → DLX.
"""

import argparse
import asyncio

import aio_pika
import structlog

from screening.adapters.workers.extraction_processor import (
    handle_applicant_extraction_requested,
)
from screening.adapters.workers.screening_processor import (
    handle_applicant_screening_requested,
)
from shared.config import Settings, setup_logging
from shared.entrypoints.bootstrap import get_screening_container
from shared.events.adapters.rabbitmq_message_consumer import RabbitMQMessageConsumer
from shared.events.router import EventRouter
from shared.events.types import (
    APPLICANT_EXTRACTION_REQUESTED_V1,
    APPLICANT_SCREENING_REQUESTED_V1,
)
from shared.events.worker import EventBusWorker

log = structlog.get_logger()


async def _run_extraction_worker() -> None:
    settings = Settings()
    setup_logging(settings.log_level)
    connection = await aio_pika.connect_robust(settings.rabbitmq_url, heartbeat=30)
    try:
        container = await get_screening_container(connection)

        router = EventRouter()
        router.on(APPLICANT_EXTRACTION_REQUESTED_V1, handle_applicant_extraction_requested)

        consumer = RabbitMQMessageConsumer(
            connection=connection,
            queue_name="applicant-extraction-queue",
            bindings=[],
            prefetch_count=5,
            dlx=settings.rabbitmq_dlx,
        )
        worker = EventBusWorker(
            consumer=consumer,
            router=router,
            context=container,
            worker_name="applicant_extraction_worker",
            use_heartbeat=False,
        )
        await worker.run()
    finally:
        await connection.close()


async def _run_screening_worker() -> None:
    settings = Settings()
    setup_logging(settings.log_level)
    connection = await aio_pika.connect_robust(settings.rabbitmq_url, heartbeat=30)
    try:
        container = await get_screening_container(connection)

        router = EventRouter()
        router.on(APPLICANT_SCREENING_REQUESTED_V1, handle_applicant_screening_requested)

        consumer = RabbitMQMessageConsumer(
            connection=connection,
            queue_name="applicant-screening-queue",
            bindings=[],
            prefetch_count=5,
            dlx=settings.rabbitmq_dlx,
        )
        worker = EventBusWorker(
            consumer=consumer,
            router=router,
            context=container,
            worker_name="screening_worker",
            use_heartbeat=False,
        )
        await worker.run()
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Applicant Screening Worker")
    parser.add_argument("--queue", choices=["extraction", "screening"], required=True)
    args = parser.parse_args()

    if args.queue == "extraction":
        asyncio.run(_run_extraction_worker())
    elif args.queue == "screening":
        asyncio.run(_run_screening_worker())


if __name__ == "__main__":
    main()
