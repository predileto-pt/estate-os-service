"""Customers domain-event worker CLI.

Consumes the per-context `customers-events-queue`, subscribed to the
APPLICANT_SCREENED.v1 SNS topic. Dispatches to
`handle_applicant_screened`, which sends the screening-complete email
to the org owner.

Runs the shared `SQSWorker` (ADR-008).
"""

import argparse
import asyncio

import aioboto3
import structlog

from customers.adapters.workers.event_processor import handle_applicant_screened
from shared.config import Settings, setup_logging
from shared.entrypoints.bootstrap import (
    get_booking_container,
    get_container,
    get_property_container,
)
from shared.events.adapters.sqs_message_consumer import SQSMessageConsumer
from shared.events.router import EventRouter
from shared.events.types import APPLICANT_SCREENED_V1
from shared.events.worker import SQSWorker

log = structlog.get_logger()


async def _run_events_worker() -> None:
    settings = Settings()
    setup_logging(settings.log_level)
    session = aioboto3.Session(
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
    )

    router = EventRouter()
    router.on(APPLICANT_SCREENED_V1, handle_applicant_screened)

    # Context dict carries per-context containers so the handler can reach
    # into the customers container for the email service.
    context = {
        "customer": await get_container(),
        "property": await get_property_container(),
        "booking": await get_booking_container(),
    }

    consumer = SQSMessageConsumer(
        session=session,
        queue_url=settings.sqs_customers_events_queue_url,
        endpoint_url=settings.aws_endpoint_url,
    )
    worker = SQSWorker(
        consumer=consumer,
        router=router,
        context=context,
        worker_name="customers_events_worker",
        use_heartbeat=True,
        heartbeat_interval=60,
        heartbeat_extension=120,
    )
    await worker.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="Customers Domain-Event Worker")
    parser.add_argument("--queue", choices=["events"], required=True)
    args = parser.parse_args()

    if args.queue == "events":
        asyncio.run(_run_events_worker())


if __name__ == "__main__":
    main()
