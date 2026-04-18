"""Contract intelligence command-queue worker CLI.

Three sub-commands, one SQS queue each:
- `--queue ingestion` consumes DOCUMENT_INGESTION_REQUESTED.v1
- `--queue analysis`  consumes DOCUMENT_ANALYSIS_REQUESTED.v1
- `--queue dlq`       consumes the DLQ (same event type as its source queue)

Runs the shared `SQSWorker` (ADR-008) with a single-handler `EventRouter`
per sub-command. DLQ handler marks failed documents as FAILED.

The DLQ worker's failure semantics are a special case: since the DLQ IS
the graveyard, a handler-raise there means "couldn't even mark as failed
in the DB". The shared worker still nacks — SQS redelivers from the DLQ
queue itself, giving us another chance. After N failures the message
sits in the DLQ's DLQ (if configured) or is lost; operationally we alert
on DLQ depth anyway.
"""

import argparse
import asyncio

import aioboto3
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
from shared.events.adapters.sqs_message_consumer import SQSMessageConsumer
from shared.events.router import EventRouter
from shared.events.types import (
    DOCUMENT_ANALYSIS_REQUESTED_V1,
    DOCUMENT_INGESTION_REQUESTED_V1,
)
from shared.events.worker import SQSWorker

log = structlog.get_logger()


def _create_boto3_session(settings: Settings) -> aioboto3.Session:
    if settings.aws_endpoint_url:
        return aioboto3.Session(
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
        )
    return aioboto3.Session(region_name=settings.aws_region)


async def _run_ingestion_worker() -> None:
    settings = Settings()
    setup_logging(settings.log_level)
    session = _create_boto3_session(settings)
    container = await get_contract_intelligence_container()

    router = EventRouter()
    router.on(DOCUMENT_INGESTION_REQUESTED_V1, handle_document_ingestion_requested)

    consumer = SQSMessageConsumer(
        session=session,
        queue_url=settings.sqs_contract_ingestion_queue_url,
        endpoint_url=settings.aws_endpoint_url,
    )
    worker = SQSWorker(
        consumer=consumer,
        router=router,
        context=container,
        worker_name="contract_ingestion_worker",
        use_heartbeat=True,
        heartbeat_interval=60,
        heartbeat_extension=120,
    )
    await worker.run()


async def _run_analysis_worker() -> None:
    settings = Settings()
    setup_logging(settings.log_level)
    session = _create_boto3_session(settings)
    container = await get_contract_intelligence_container()

    router = EventRouter()
    router.on(DOCUMENT_ANALYSIS_REQUESTED_V1, handle_document_analysis_requested)

    consumer = SQSMessageConsumer(
        session=session,
        queue_url=settings.sqs_contract_analysis_queue_url,
        endpoint_url=settings.aws_endpoint_url,
    )
    worker = SQSWorker(
        consumer=consumer,
        router=router,
        context=container,
        worker_name="contract_analysis_worker",
        use_heartbeat=True,
        heartbeat_interval=60,
        heartbeat_extension=120,
    )
    await worker.run()


async def _run_dlq_worker(queue_url: str, worker_name: str) -> None:
    settings = Settings()
    setup_logging(settings.log_level)
    session = _create_boto3_session(settings)
    container = await get_contract_intelligence_container()

    # DLQ handler marks the source document as FAILED. Both ingestion and
    # analysis DLQs carry the same envelope shape (data.document_id); the
    # handler is identical regardless of which original event type landed
    # in the DLQ.
    router = EventRouter()
    router.on(DOCUMENT_INGESTION_REQUESTED_V1, handle_contract_document_dlq)
    router.on(DOCUMENT_ANALYSIS_REQUESTED_V1, handle_contract_document_dlq)

    consumer = SQSMessageConsumer(
        session=session,
        queue_url=queue_url,
        endpoint_url=settings.aws_endpoint_url,
    )
    worker = SQSWorker(
        consumer=consumer,
        router=router,
        context=container,
        worker_name=worker_name,
        use_heartbeat=False,
    )
    await worker.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="Contract Intelligence SQS Worker")
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
        settings = Settings()
        asyncio.run(
            _run_dlq_worker(
                settings.sqs_contract_ingestion_dlq_url, "contract_ingestion_dlq_worker"
            )
        )
    elif args.queue == "analysis-dlq":
        settings = Settings()
        asyncio.run(
            _run_dlq_worker(settings.sqs_contract_analysis_dlq_url, "contract_analysis_dlq_worker")
        )


if __name__ == "__main__":
    main()
