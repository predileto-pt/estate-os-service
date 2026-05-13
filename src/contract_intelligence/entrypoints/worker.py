"""Contract intelligence command-queue worker CLI.

Three sub-commands, one queue each:
- `--queue ingestion` consumes DOCUMENT_INGESTION_REQUESTED.v1
- `--queue analysis`  consumes DOCUMENT_ANALYSIS_REQUESTED.v1
- `--queue dlq`       consumes the DLQ (same event type as its source queue)

Runs the shared `EventBusWorker` (ADR-008) with a single-handler `EventRouter`
per sub-command. DLQ handler marks failed documents as FAILED.

The DLQ worker's failure semantics are a special case: since the DLQ IS
the graveyard, a handler-raise there means "couldn't even mark as failed
in the DB". The shared worker still nacks — broker requeues per the
queue's `x-delivery-limit`, giving us another chance. Operationally we
alert on DLQ depth anyway.
"""

import argparse
import asyncio

import aio_pika
import structlog

from contract_intelligence.adapters.workers.analysis_processor import (
    handle_document_analysis_requested,
)
from contract_intelligence.adapters.workers.dlq_processor import (
    handle_contract_document_dlq,
)
from contract_intelligence.adapters.workers.ingestion_processor import (
    handle_document_ingestion_requested,
)
from shared.config import Settings, setup_logging
from shared.entrypoints.bootstrap import get_contract_intelligence_container
from shared.events.adapters.rabbitmq_message_consumer import RabbitMQMessageConsumer
from shared.events.router import EventRouter
from shared.events.types import (
    DOCUMENT_ANALYSIS_REQUESTED_V1,
    DOCUMENT_INGESTION_REQUESTED_V1,
)
from shared.events.worker import EventBusWorker

log = structlog.get_logger()


async def _run_ingestion_worker() -> None:
    settings = Settings()
    setup_logging(settings.log_level)
    connection = await aio_pika.connect_robust(settings.rabbitmq_url, heartbeat=30)
    try:
        container = await get_contract_intelligence_container(connection)

        router = EventRouter()
        router.on(DOCUMENT_INGESTION_REQUESTED_V1, handle_document_ingestion_requested)

        consumer = RabbitMQMessageConsumer(
            connection=connection,
            queue_name="contract-ingestion-queue",
            bindings=[],
            prefetch_count=5,
            dlx=settings.rabbitmq_dlx,
        )
        worker = EventBusWorker(
            consumer=consumer,
            router=router,
            context=container,
            worker_name="contract_ingestion_worker",
            use_heartbeat=False,
        )
        await worker.run()
    finally:
        await connection.close()


async def _run_analysis_worker() -> None:
    settings = Settings()
    setup_logging(settings.log_level)
    connection = await aio_pika.connect_robust(settings.rabbitmq_url, heartbeat=30)
    try:
        container = await get_contract_intelligence_container(connection)

        router = EventRouter()
        router.on(DOCUMENT_ANALYSIS_REQUESTED_V1, handle_document_analysis_requested)

        consumer = RabbitMQMessageConsumer(
            connection=connection,
            queue_name="contract-analysis-queue",
            bindings=[],
            prefetch_count=5,
            dlx=settings.rabbitmq_dlx,
        )
        worker = EventBusWorker(
            consumer=consumer,
            router=router,
            context=container,
            worker_name="contract_analysis_worker",
            use_heartbeat=False,
        )
        await worker.run()
    finally:
        await connection.close()


async def _run_dlq_worker(queue_name: str, worker_name: str) -> None:
    settings = Settings()
    setup_logging(settings.log_level)
    connection = await aio_pika.connect_robust(settings.rabbitmq_url, heartbeat=30)
    try:
        container = await get_contract_intelligence_container(connection)

        # DLQ handler marks the source document as FAILED. Both ingestion
        # and analysis DLQs carry the same envelope shape; the handler is
        # identical regardless of which original event type landed.
        router = EventRouter()
        router.on(DOCUMENT_INGESTION_REQUESTED_V1, handle_contract_document_dlq)
        router.on(DOCUMENT_ANALYSIS_REQUESTED_V1, handle_contract_document_dlq)

        consumer = RabbitMQMessageConsumer(
            connection=connection,
            queue_name=queue_name,
            bindings=[],
            prefetch_count=5,
            dlx=settings.rabbitmq_dlx,
        )
        worker = EventBusWorker(
            consumer=consumer,
            router=router,
            context=container,
            worker_name=worker_name,
            use_heartbeat=False,
        )
        await worker.run()
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Contract Intelligence Worker")
    parser.add_argument(
        "--queue",
        choices=["ingestion", "analysis", "ingestion-dlq", "analysis-dlq"],
        required=True,
    )
    args = parser.parse_args()

    if args.queue == "ingestion":
        asyncio.run(_run_ingestion_worker())
    elif args.queue == "analysis":
        asyncio.run(_run_analysis_worker())
    elif args.queue == "ingestion-dlq":
        asyncio.run(
            _run_dlq_worker(
                "dead-letters",  # global DLX-bound queue
                "contract_ingestion_dlq_worker",
            )
        )
    elif args.queue == "analysis-dlq":
        asyncio.run(
            _run_dlq_worker(
                "dead-letters",
                "contract_analysis_dlq_worker",
            )
        )


if __name__ == "__main__":
    main()
