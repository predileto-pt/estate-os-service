import argparse
import asyncio
import json
import signal
from typing import Any

import aioboto3
import structlog

from screening.adapters.workers import extraction_processor, screening_processor
from shared.config import Settings, setup_logging
from shared.entrypoints.bootstrap import get_screening_container

log = structlog.get_logger()


class SQSWorker:
    def __init__(
        self,
        session: aioboto3.Session,
        queue_url: str,
        container,
        processor,
        endpoint_url: str | None = None,
        worker_name: str = "sqs_worker",
    ) -> None:
        self._session = session
        self._queue_url = queue_url
        self._container = container
        self._processor = processor
        self._endpoint_url = endpoint_url
        self._worker_name = worker_name
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
                    await self._processor.process_event(msg["body"], self._container)
                    await self._delete_message(msg["receipt_handle"])
                    log.info(f"{self._worker_name}_message_processed")
            except Exception:
                log.exception(f"{self._worker_name}_error")
                await asyncio.sleep(5)

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


async def _run_extraction_worker() -> None:
    settings = Settings()
    setup_logging(settings.log_level)
    session = aioboto3.Session(
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
    )
    container = await get_screening_container()
    worker = SQSWorker(
        session,
        settings.sqs_applicant_extraction_queue_url,
        container,
        processor=extraction_processor,
        endpoint_url=settings.aws_endpoint_url,
        worker_name="applicant_extraction_worker",
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
    worker = SQSWorker(
        session,
        settings.sqs_applicant_screening_queue_url,
        container,
        processor=screening_processor,
        endpoint_url=settings.aws_endpoint_url,
        worker_name="screening_worker",
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
