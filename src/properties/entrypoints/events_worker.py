"""Properties domain-event worker CLI.

Consumes the per-context `properties-events-queue`, which is subscribed
to the SNS topics this context cares about (PROPERTY_CREATED.v1 →
amenity discovery).

Distinct from `properties/entrypoints/worker.py`, which consumes the
extraction command queue.

Runs the shared `SQSWorker` (ADR-008).
"""

import asyncio

import aioboto3
import structlog

from properties.adapters.workers.discovery_processor import handle_property_created
from shared.config import Settings, setup_logging
from shared.entrypoints.bootstrap import (
    get_booking_container,
    get_container,
    get_property_container,
)
from shared.events.adapters.sqs_message_consumer import SQSMessageConsumer
from shared.events.router import EventRouter
from shared.events.types import PROPERTY_CREATED_V1
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
    router.on(PROPERTY_CREATED_V1, handle_property_created)

    context = {
        "property": await get_property_container(),
        "customer": await get_container(),
        "booking": await get_booking_container(),
    }

    consumer = SQSMessageConsumer(
        session=session,
        queue_url=settings.sqs_properties_events_queue_url,
        endpoint_url=settings.aws_endpoint_url,
    )
    worker = SQSWorker(
        consumer=consumer,
        router=router,
        context=context,
        worker_name="properties_events_worker",
        use_heartbeat=True,
        heartbeat_interval=60,
        heartbeat_extension=120,
    )
    await worker.run()


def main() -> None:
    asyncio.run(_run_events_worker())


if __name__ == "__main__":
    main()
