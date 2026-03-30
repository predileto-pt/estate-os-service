"""Unified domain events worker.

Polls the single domain events queue and routes events to handlers
registered from all bounded contexts.

Usage:
    python -m shared.entrypoints.events_worker
"""

import asyncio
import json
import signal

import aioboto3
import structlog

from shared.config import Settings, setup_logging
from shared.events.base import DomainEvent
from shared.events.router import EventRouter
from shared.events import types as event_types

log = structlog.get_logger()


def _build_router() -> EventRouter:
    """Register all cross-context event handlers."""
    from booking_management.adapters.events.handlers import handle_applicant_screened
    from customer_management.adapters.workers.event_processor import (
        _handle_applicant_screened as cm_handle_applicant_screened,
    )
    from property_management.adapters.workers.discovery_processor import (
        handle_property_created,
    )

    router = EventRouter()
    router.on(event_types.APPLICANT_SCREENED, cm_handle_applicant_screened)
    router.on(event_types.APPLICANT_SCREENED, handle_applicant_screened)
    router.on(event_types.PROPERTY_CREATED, handle_property_created)
    return router


async def _build_context() -> dict:
    """Bootstrap all containers needed by event handlers."""
    from shared.entrypoints.bootstrap import (
        get_booking_container,
        get_container,
        get_property_container,
    )

    return {
        "customer": await get_container(),
        "property": await get_property_container(),
        "booking": await get_booking_container(),
    }


class DomainEventsWorker:
    def __init__(
        self,
        session: aioboto3.Session,
        queue_url: str,
        router: EventRouter,
        context: dict,
        endpoint_url: str | None = None,
    ) -> None:
        self._session = session
        self._queue_url = queue_url
        self._router = router
        self._context = context
        self._endpoint_url = endpoint_url
        self._running = True

    def _client_kwargs(self) -> dict:
        kwargs: dict = {}
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url
        return kwargs

    def _shutdown(self) -> None:
        log.info("domain_events_worker_shutting_down")
        self._running = False

    async def run(self) -> None:
        log.info("domain_events_worker_started", queue_url=self._queue_url)

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._shutdown)

        while self._running:
            try:
                async with self._session.client("sqs", **self._client_kwargs()) as sqs:
                    response = await sqs.receive_message(
                        QueueUrl=self._queue_url,
                        MaxNumberOfMessages=1,
                        WaitTimeSeconds=20,
                    )
                    messages = response.get("Messages", [])
                    for msg in messages:
                        body = json.loads(msg["Body"])
                        event = DomainEvent.from_dict(body)
                        log.info(
                            "domain_event_received",
                            event_type=event.event_type,
                            event_id=event.event_id,
                        )
                        await self._router.dispatch(event, self._context)
                        await sqs.delete_message(
                            QueueUrl=self._queue_url,
                            ReceiptHandle=msg["ReceiptHandle"],
                        )
                        log.info(
                            "domain_event_processed",
                            event_type=event.event_type,
                            event_id=event.event_id,
                        )
            except Exception:
                log.exception("domain_events_worker_error")
                await asyncio.sleep(5)


async def _main() -> None:
    settings = Settings()
    setup_logging(settings.log_level)

    router = _build_router()
    context = await _build_context()

    session = aioboto3.Session(
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
    )

    worker = DomainEventsWorker(
        session=session,
        queue_url=settings.sqs_domain_events_queue_url,
        router=router,
        context=context,
        endpoint_url=settings.aws_endpoint_url,
    )
    await worker.run()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
