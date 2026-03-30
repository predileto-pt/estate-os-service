import asyncio
import signal

import structlog

from customers.adapters.queue.sqs_consumer import SQSMessageConsumer
from customers.adapters.workers.event_processor import process_event

log = structlog.get_logger()


class EventsWorker:
    def __init__(self, consumer: SQSMessageConsumer, queue_url: str, container) -> None:
        self._consumer = consumer
        self._queue_url = queue_url
        self._container = container
        self._running = True

    async def run(self) -> None:
        log.info("events_worker_started", queue_url=self._queue_url)

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._shutdown)

        while self._running:
            try:
                messages = await self._consumer.poll(self._queue_url)
                for msg in messages:
                    await process_event(msg["body"], self._container)
                    await self._consumer.delete_message(self._queue_url, msg["receipt_handle"])
                    log.info("event_message_processed", event_type=msg["body"].get("event_type"))
            except Exception:
                log.exception("events_worker_error")
                await asyncio.sleep(5)

    def _shutdown(self) -> None:
        log.info("events_worker_shutting_down")
        self._running = False
