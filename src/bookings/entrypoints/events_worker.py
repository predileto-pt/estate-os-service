"""Bookings domain-event worker CLI.

Consumes APPLICANT_SCREENED.v1 and creates a booking applicant. Today
reads from the shared `sqs_domain_events_queue`; the SNS fan-out spec
will rewire it to a dedicated `bookings-events-queue` subscribed to
just the APPLICANT_SCREENED.v1 topic.

Runs the shared `SQSWorker` (ADR-008).
"""

import asyncio

import aioboto3
import structlog

from bookings.adapters.events.handlers import handle_applicant_screened
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

    context = {
        "booking": await get_booking_container(),
        "customer": await get_container(),
        "property": await get_property_container(),
    }

    consumer = SQSMessageConsumer(
        session=session,
        queue_url=settings.sqs_domain_events_queue_url,
        endpoint_url=settings.aws_endpoint_url,
    )
    worker = SQSWorker(
        consumer=consumer,
        router=router,
        context=context,
        worker_name="bookings_events_worker",
        use_heartbeat=True,
        heartbeat_interval=60,
        heartbeat_extension=120,
    )
    await worker.run()


def main() -> None:
    asyncio.run(_run_events_worker())


if __name__ == "__main__":
    main()
