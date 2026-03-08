import argparse
import asyncio

import aioboto3
import structlog

from core_api.adapters.queue.sqs_consumer import SQSMessageConsumer
from core_api.adapters.workers.events_worker import EventsWorker
from core_api.config import Settings
from core_api.entrypoints.bootstrap import get_container

log = structlog.get_logger()


async def _run_events_worker() -> None:
    settings = Settings()
    session = aioboto3.Session(
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
    )
    consumer = SQSMessageConsumer(session, endpoint_url=settings.aws_endpoint_url)
    container = await get_container()
    worker = EventsWorker(consumer, settings.sqs_events_queue_url, container)
    await worker.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="Core API SQS Worker")
    parser.add_argument("--queue", choices=["events"], required=True)
    args = parser.parse_args()

    if args.queue == "events":
        asyncio.run(_run_events_worker())


if __name__ == "__main__":
    main()
