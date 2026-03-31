import argparse
import asyncio
import json
import signal
import time
from typing import Any

import aioboto3
import structlog

from contract_intelligence.adapters.workers import (
    analysis_processor,
    dlq_processor,
    ingestion_processor,
)
from shared.config import Settings, setup_logging

log = structlog.get_logger()


async def _heartbeat(
    session: aioboto3.Session,
    queue_url: str,
    receipt_handle: str,
    endpoint_url: str | None = None,
    interval: int = 60,
    extension: int = 120,
) -> None:
    """Periodically extend message visibility while processing."""
    extensions = 0
    kwargs: dict[str, Any] = {}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url

    try:
        while True:
            await asyncio.sleep(interval)
            try:
                async with session.client("sqs", **kwargs) as sqs:
                    await sqs.change_message_visibility(
                        QueueUrl=queue_url,
                        ReceiptHandle=receipt_handle,
                        VisibilityTimeout=extension,
                    )
                extensions += 1
                log.debug("heartbeat_extended", queue_url=queue_url, extensions=extensions)
            except Exception:
                log.warning(
                    "heartbeat_extension_failed", queue_url=queue_url, extensions=extensions
                )
    except asyncio.CancelledError:
        log.debug("heartbeat_stopped", queue_url=queue_url, total_extensions=extensions)


class SQSWorker:
    def __init__(
        self,
        session: aioboto3.Session,
        queue_url: str,
        container: Any,
        processor: Any,
        endpoint_url: str | None = None,
        worker_name: str = "sqs_worker",
        use_heartbeat: bool = False,
        heartbeat_interval: int = 60,
        heartbeat_extension: int = 120,
    ) -> None:
        self._session = session
        self._queue_url = queue_url
        self._container = container
        self._processor = processor
        self._endpoint_url = endpoint_url
        self._worker_name = worker_name
        self._use_heartbeat = use_heartbeat
        self._heartbeat_interval = heartbeat_interval
        self._heartbeat_extension = heartbeat_extension
        self._running = True

    async def run(self) -> None:
        log.info(f"{self._worker_name}_started", queue_url=self._queue_url)

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._shutdown)

        while self._running:
            try:
                messages = await self._poll()
                for msg in messages:
                    await self._process_message(msg)
            except Exception:
                log.exception(f"{self._worker_name}_error")
                await asyncio.sleep(5)

    async def _process_message(self, msg: dict[str, Any]) -> None:
        heartbeat_task = None
        start = time.monotonic()

        if self._use_heartbeat:
            heartbeat_task = asyncio.create_task(
                _heartbeat(
                    self._session,
                    self._queue_url,
                    msg["receipt_handle"],
                    endpoint_url=self._endpoint_url,
                    interval=self._heartbeat_interval,
                    extension=self._heartbeat_extension,
                )
            )

        try:
            await self._processor.process_event(msg["body"], self._container)
            elapsed = time.monotonic() - start
            log.info(
                f"{self._worker_name}_message_processed",
                processing_seconds=round(elapsed, 2),
            )
        except Exception:
            log.exception(f"{self._worker_name}_message_error", raw_body=msg.get("body"))
        finally:
            # Always delete the message — failed documents stay in their current
            # status (UPLOADED/PARSED) and can be re-queued manually.
            await self._delete_message(msg["receipt_handle"])
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)

    async def _poll(self) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {}
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url

        async with self._session.client("sqs", **kwargs) as sqs:
            response = await sqs.receive_message(
                QueueUrl=self._queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,
            )
            messages = response.get("Messages", [])
            return [
                {
                    "body": json.loads(msg["Body"]),
                    "receipt_handle": msg["ReceiptHandle"],
                }
                for msg in messages
            ]

    async def _delete_message(self, receipt_handle: str) -> None:
        kwargs: dict[str, Any] = {}
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url

        async with self._session.client("sqs", **kwargs) as sqs:
            await sqs.delete_message(QueueUrl=self._queue_url, ReceiptHandle=receipt_handle)

    def _shutdown(self) -> None:
        log.info(f"{self._worker_name}_shutting_down")
        self._running = False


async def _run_ingestion_worker() -> None:
    settings = Settings()
    setup_logging(settings.log_level)
    session = _create_boto3_session(settings)

    from shared.entrypoints.bootstrap import get_contract_intelligence_container

    container = await get_contract_intelligence_container()
    worker = SQSWorker(
        session,
        settings.sqs_contract_ingestion_queue_url,
        container,
        processor=ingestion_processor,
        endpoint_url=settings.aws_endpoint_url,
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

    from shared.entrypoints.bootstrap import get_contract_intelligence_container

    container = await get_contract_intelligence_container()
    worker = SQSWorker(
        session,
        settings.sqs_contract_analysis_queue_url,
        container,
        processor=analysis_processor,
        endpoint_url=settings.aws_endpoint_url,
        worker_name="contract_analysis_worker",
        use_heartbeat=True,
        heartbeat_interval=60,
        heartbeat_extension=120,
    )
    await worker.run()


async def _run_dlq_worker() -> None:
    settings = Settings()
    setup_logging(settings.log_level)
    session = _create_boto3_session(settings)

    from shared.entrypoints.bootstrap import get_contract_intelligence_container

    container = await get_contract_intelligence_container()
    worker = SQSWorker(
        session,
        settings.sqs_contract_dlq_url,
        container,
        processor=dlq_processor,
        endpoint_url=settings.aws_endpoint_url,
        worker_name="contract_dlq_worker",
        use_heartbeat=False,
    )
    await worker.run()


def _create_boto3_session(settings: Settings) -> aioboto3.Session:
    if settings.aws_endpoint_url:
        return aioboto3.Session(
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
        )
    return aioboto3.Session(region_name=settings.aws_region)


def main() -> None:
    parser = argparse.ArgumentParser(description="Contract Intelligence SQS Worker")
    parser.add_argument("--queue", choices=["ingestion", "analysis", "dlq"], required=True)
    args = parser.parse_args()

    if args.queue == "ingestion":
        asyncio.run(_run_ingestion_worker())
    elif args.queue == "analysis":
        asyncio.run(_run_analysis_worker())
    elif args.queue == "dlq":
        asyncio.run(_run_dlq_worker())


if __name__ == "__main__":
    main()
