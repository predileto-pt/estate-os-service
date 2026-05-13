"""Customers/organizations domain-event worker CLI.

Consumes the per-context `customers-events-queue`, bound to the
`APPLICANT_SCREENED.v1` event on the `domain-events` topic exchange.
Dispatches to `handle_applicant_screened`, which sends the
screening-complete email to the org owner.

Runs the shared `EventBusWorker` (ADR-008).
"""

import argparse
import asyncio

import aio_pika
import structlog

from organizations.adapters.workers.event_processor import handle_applicant_screened
from shared.config import Settings, setup_logging
from shared.entrypoints.bootstrap import (
    get_booking_container,
    get_container,
    get_property_container,
)
from shared.events.adapters.rabbitmq_message_consumer import RabbitMQMessageConsumer
from shared.events.router import EventRouter
from shared.events.types import APPLICANT_SCREENED_V1
from shared.events.worker import EventBusWorker

log = structlog.get_logger()


async def _run_events_worker() -> None:
    settings = Settings()
    setup_logging(settings.log_level)
    connection = await aio_pika.connect_robust(settings.rabbitmq_url, heartbeat=30)
    try:
        router = EventRouter()
        router.on(APPLICANT_SCREENED_V1, handle_applicant_screened)

        # Context dict carries per-context containers so the handler can
        # reach into the customers container for the email service.
        context = {
            "customer": await get_container(),
            "property": await get_property_container(connection),
            "booking": await get_booking_container(),
        }

        consumer = RabbitMQMessageConsumer(
            connection=connection,
            queue_name="customers-events-queue",
            bindings=[
                (settings.rabbitmq_domain_events_exchange, "APPLICANT_SCREENED.v1"),
            ],
            prefetch_count=5,
            dlx=settings.rabbitmq_dlx,
        )
        worker = EventBusWorker(
            consumer=consumer,
            router=router,
            context=context,
            worker_name="customers_events_worker",
            use_heartbeat=False,
        )
        await worker.run()
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Customers Domain-Event Worker")
    parser.add_argument("--queue", choices=["events"], required=True)
    args = parser.parse_args()

    if args.queue == "events":
        asyncio.run(_run_events_worker())


if __name__ == "__main__":
    main()
