"""Shared event-bus worker.

One `EventBusWorker` class. Every context — domain-event consumers AND
command-queue consumers — reuses it. ADR-006 semantics: client reuse,
batch polling, bounded concurrency, contextvars, heartbeat, drain.

Failure semantics (single rule for every worker):

    handler raises → worker nacks → broker redelivers up to the queue's
    delivery limit → message lands in the queue's DLQ.
"""

import asyncio
import os
import signal
import time
from typing import Any

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

from shared.events.ports import Message, MessageConsumer
from shared.events.router import EventRouter

log = structlog.get_logger()


async def _heartbeat(msg: Message, interval: int, extension: int) -> None:
    """Periodically extend message visibility while a handler runs.

    Reuses the shared SQS client via `msg.extend_visibility` — no new
    client per heartbeat tick.
    """
    extensions = 0
    try:
        while True:
            await asyncio.sleep(interval)
            try:
                await msg.extend_visibility(extension)
                extensions += 1
                log.debug("heartbeat_extended", extensions=extensions)
            except Exception:
                log.warning("heartbeat_extension_failed", extensions=extensions)
    except asyncio.CancelledError:
        log.debug("heartbeat_stopped", total_extensions=extensions)


class EventBusWorker:
    """Port-based worker. See module docstring for failure semantics."""

    def __init__(
        self,
        consumer: MessageConsumer,
        router: EventRouter,
        context: Any,
        worker_name: str,
        use_heartbeat: bool = True,
        heartbeat_interval: int = 60,
        heartbeat_extension: int = 120,
        max_concurrency: int = 5,
        max_messages_per_poll: int = 10,
        wait_seconds: int = 20,
        drain_timeout: int = 30,
    ) -> None:
        self._consumer = consumer
        self._router = router
        self._context = context
        self._worker_name = worker_name
        self._use_heartbeat = use_heartbeat
        self._heartbeat_interval = heartbeat_interval
        self._heartbeat_extension = heartbeat_extension
        self._max_concurrency = max_concurrency
        self._max_messages_per_poll = max_messages_per_poll
        self._wait_seconds = wait_seconds
        self._drain_timeout = drain_timeout
        self._running = True
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._in_flight: list[asyncio.Task] = []

    async def run(self) -> None:
        log.info(
            f"{self._worker_name}_started",
            max_concurrency=self._max_concurrency,
            max_messages_per_poll=self._max_messages_per_poll,
        )

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self._shutdown)
            except NotImplementedError:
                # Signal handling is not available in all environments (e.g. Windows,
                # some embedded loops used in tests). The worker still stops when
                # `_running` is flipped externally.
                pass

        async with self._consumer as consumer:
            while self._running:
                try:
                    messages = await consumer.poll(
                        max_messages=self._max_messages_per_poll,
                        wait_seconds=self._wait_seconds,
                    )
                    if not messages:
                        continue

                    self._in_flight = [
                        asyncio.create_task(self._bounded_process(m)) for m in messages
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

    async def _bounded_process(self, msg: Message) -> None:
        async with self._semaphore:
            await self._process_message(msg)

    async def _process_message(self, msg: Message) -> None:
        # contextvars here are for LOGGING ONLY — they bind fields onto every
        # structlog emission inside this task. The handler itself receives the
        # full DomainEvent as an argument via `_router.dispatch`; it must NOT
        # read these back via `structlog.contextvars.get_contextvars()`.
        clear_contextvars()
        bind_contextvars(
            worker=self._worker_name,
            message_id=msg.message_id,
            event_id=msg.event.event_id,
            event_type=msg.event.event_type,
        )

        heartbeat_task: asyncio.Task | None = None
        if self._use_heartbeat:
            heartbeat_task = asyncio.create_task(
                _heartbeat(
                    msg,
                    interval=self._heartbeat_interval,
                    extension=self._heartbeat_extension,
                )
            )

        start = time.monotonic()
        try:
            # EventRouter calls `await handler(msg.event, self._context)`.
            # Handler signature: (event: DomainEvent, context: Any) -> None.
            await self._router.dispatch(msg.event, self._context)
            elapsed = time.monotonic() - start
            log.info(
                f"{self._worker_name}_message_processed",
                processing_seconds=round(elapsed, 2),
                status="success",
            )
            await msg.ack()
        except Exception as exc:
            elapsed = time.monotonic() - start
            log.exception(
                f"{self._worker_name}_message_error",
                processing_seconds=round(elapsed, 2),
                status="error",
                error_type=type(exc).__name__,
            )
            await msg.nack()
        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)
            clear_contextvars()

    def _shutdown(self) -> None:
        # Go-style two-strike shutdown:
        # - First SIGINT / SIGTERM: flip _running, let the poll loop drain
        #   in-flight handlers up to drain_timeout.
        # - Second signal: brutally kill the process via os._exit. No atexit
        #   hooks run, no buffers flush, no drain — pid dies immediately.
        #   Unacked broker messages stay unacked → redelivered to the next
        #   consumer attach (safe by construction).
        if not self._running:
            log.warning(
                f"{self._worker_name}_force_quit",
                in_flight=len(self._in_flight),
            )
            os._exit(130)  # 128 + SIGINT
        log.info(
            f"{self._worker_name}_shutting_down",
            hint="ctrl-c again to force quit",
        )
        self._running = False
