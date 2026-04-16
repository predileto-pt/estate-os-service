import argparse
import asyncio
import json
import signal
import time
from typing import Any
from uuid import UUID

import aioboto3
import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

from properties.adapters.workers import extraction_processor
from shared.config import Settings, setup_logging
from shared.entrypoints.bootstrap import get_property_container

log = structlog.get_logger()


async def _heartbeat(
    sqs: Any,
    queue_url: str,
    receipt_handle: str,
    interval: int = 60,
    extension: int = 120,
) -> None:
    """Periodically extend message visibility while processing.

    Reuses the worker's shared SQS client — no new client per heartbeat tick.
    """
    extensions = 0
    try:
        while True:
            await asyncio.sleep(interval)
            try:
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
        max_concurrency: int = 5,
        max_messages_per_poll: int = 10,
        drain_timeout: int = 30,
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
        self._max_concurrency = max_concurrency
        self._max_messages_per_poll = max_messages_per_poll
        self._drain_timeout = drain_timeout
        self._running = True
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._in_flight: list[asyncio.Task] = []
        self._sqs: Any = None

    async def run(self) -> None:
        log.info(
            f"{self._worker_name}_started",
            queue_url=self._queue_url,
            max_concurrency=self._max_concurrency,
            max_messages_per_poll=self._max_messages_per_poll,
        )

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._shutdown)

        kwargs: dict[str, Any] = {}
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url

        # Single SQS client reused for the entire worker lifetime — avoids
        # per-call TLS handshake and credential resolution overhead. Safe to
        # share across concurrent coroutines.
        async with self._session.client("sqs", **kwargs) as sqs:
            self._sqs = sqs

            while self._running:
                try:
                    messages = await self._poll()
                    if not messages:
                        continue

                    self._in_flight = [
                        asyncio.create_task(self._bounded_process(msg)) for msg in messages
                    ]
                    await asyncio.gather(*self._in_flight, return_exceptions=True)
                    self._in_flight = []
                except Exception:
                    log.exception(f"{self._worker_name}_error")
                    await asyncio.sleep(5)

            await self._drain()

    async def _drain(self) -> None:
        if not self._in_flight:
            return
        log.info(f"{self._worker_name}_draining", in_flight=len(self._in_flight))
        done, pending = await asyncio.wait(self._in_flight, timeout=self._drain_timeout)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        log.info(
            f"{self._worker_name}_drain_complete",
            completed=len(done),
            cancelled=len(pending),
        )

    async def _bounded_process(self, msg: dict[str, Any]) -> None:
        async with self._semaphore:
            await self._process_message(msg)

    async def _process_message(self, msg: dict[str, Any]) -> None:
        clear_contextvars()
        body = msg["body"] if isinstance(msg["body"], dict) else {}
        data = body.get("data", {}) if isinstance(body.get("data"), dict) else {}
        bind_contextvars(
            worker=self._worker_name,
            message_id=msg.get("message_id"),
            job_id=data.get("job_id"),
            event_type=body.get("event_type"),
        )

        heartbeat_task: asyncio.Task | None = None
        start = time.monotonic()

        if self._use_heartbeat:
            heartbeat_task = asyncio.create_task(
                _heartbeat(
                    self._sqs,
                    self._queue_url,
                    msg["receipt_handle"],
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
                status="success",
            )
        except Exception as exc:
            elapsed = time.monotonic() - start
            log.exception(
                f"{self._worker_name}_message_error",
                processing_seconds=round(elapsed, 2),
                status="error",
                error_type=type(exc).__name__,
                raw_body=msg.get("body"),
            )
        finally:
            # Always delete the message — failed jobs stay in their current
            # status and can be re-queued via --retry-job.
            try:
                await self._delete_message(msg["receipt_handle"])
            except Exception:
                log.exception(f"{self._worker_name}_delete_failed")
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)
            clear_contextvars()

    async def _poll(self) -> list[dict[str, Any]]:
        response = await self._sqs.receive_message(
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=self._max_messages_per_poll,
            WaitTimeSeconds=20,
        )
        messages = response.get("Messages", [])
        return [
            {
                "body": json.loads(msg["Body"]),
                "receipt_handle": msg["ReceiptHandle"],
                "message_id": msg.get("MessageId"),
            }
            for msg in messages
        ]

    async def _delete_message(self, receipt_handle: str) -> None:
        await self._sqs.delete_message(QueueUrl=self._queue_url, ReceiptHandle=receipt_handle)

    def _shutdown(self) -> None:
        log.info(f"{self._worker_name}_shutting_down")
        self._running = False


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
    worker = SQSWorker(
        session,
        settings.sqs_property_extraction_queue_url,
        container,
        processor=extraction_processor,
        endpoint_url=settings.aws_endpoint_url,
        worker_name="extraction_worker",
        use_heartbeat=True,
        heartbeat_interval=60,
        heartbeat_extension=120,
    )
    await worker.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="Property Management SQS Worker")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--queue", choices=["extraction"])
    group.add_argument("--retry-job", metavar="JOB_ID", help="Retry a failed extraction job")
    args = parser.parse_args()

    if args.retry_job:
        asyncio.run(_retry_extraction_job(args.retry_job))
    elif args.queue == "extraction":
        asyncio.run(_run_extraction_worker())


if __name__ == "__main__":
    main()
