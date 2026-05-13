"""Shared EventBusWorker — ack/nack/heartbeat/drain behaviour.

Uses `InMemoryMessageConsumer` to drive the worker deterministically.
"""

import asyncio

from shared.events.adapters.inmemory_event_bus import (
    InMemoryMessage,
    InMemoryMessageConsumer,
)
from shared.events.base import DomainEvent
from shared.events.router import EventRouter
from shared.events.worker import EventBusWorker


def _event(event_type: str = "X.v1") -> DomainEvent:
    return DomainEvent(event_type=event_type, data={"foo": "bar"})


async def _run_one_loop(worker: EventBusWorker) -> None:
    """Stop the worker after one successful poll cycle.

    We use a side-channel: set `_running = False` before entering the loop so
    the worker's `while self._running:` block executes exactly once and then
    drains.
    """

    async def _stop_after_first_poll() -> None:
        # Give the worker one loop iteration; then flip the flag so the next
        # `await consumer.poll` returns an empty batch and the loop exits.
        await asyncio.sleep(0)
        worker._running = False  # noqa: SLF001 — test helper

    await asyncio.gather(worker.run(), _stop_after_first_poll())


class TestHandlerSuccess:
    async def test_ack_after_handler_returns(self) -> None:
        consumer = InMemoryMessageConsumer()
        consumer.enqueue(_event("OK.v1"))

        received: list[DomainEvent] = []

        async def handler(event: DomainEvent, ctx: dict) -> None:
            received.append(event)

        router = EventRouter()
        router.on("OK.v1", handler)

        worker = EventBusWorker(
            consumer=consumer,
            router=router,
            context={},
            worker_name="test_worker",
            use_heartbeat=False,
            max_concurrency=1,
            max_messages_per_poll=1,
            wait_seconds=0,
        )

        await _run_one_loop(worker)

        assert [e.event_type for e in received] == ["OK.v1"]
        assert consumer.acked == ["msg-1"]
        assert consumer.pending == []


class TestHandlerFailure:
    async def test_nack_on_unhandled_exception(self) -> None:
        consumer = InMemoryMessageConsumer()
        consumer.enqueue(_event("FAIL.v1"))

        async def handler(event: DomainEvent, ctx: dict) -> None:
            raise RuntimeError("boom")

        router = EventRouter()
        router.on("FAIL.v1", handler)

        worker = EventBusWorker(
            consumer=consumer,
            router=router,
            context={},
            worker_name="test_worker",
            use_heartbeat=False,
            max_concurrency=1,
            max_messages_per_poll=1,
            wait_seconds=0,
        )

        await _run_one_loop(worker)

        # No ack — SQS would redeliver after visibility timeout expires.
        assert consumer.acked == []
        # nack re-queues for this in-memory bus (real SQS relies on visibility
        # timeout, the invariant is equivalent: message is NOT ack'd).
        assert len(consumer.pending) == 1

    async def test_handler_for_unknown_event_type_does_not_nack(self) -> None:
        # When no handler matches, EventRouter logs a warning but doesn't raise.
        # The worker treats this as success and ack's (the message has been
        # "handled" as far as this consumer is concerned).
        consumer = InMemoryMessageConsumer()
        consumer.enqueue(_event("UNKNOWN.v1"))

        router = EventRouter()  # no handlers registered

        worker = EventBusWorker(
            consumer=consumer,
            router=router,
            context={},
            worker_name="test_worker",
            use_heartbeat=False,
            max_concurrency=1,
            max_messages_per_poll=1,
            wait_seconds=0,
        )

        await _run_one_loop(worker)

        assert consumer.acked == ["msg-1"]


class TestHeartbeat:
    async def test_heartbeat_calls_extend_visibility_during_slow_handler(self) -> None:
        # A handler that sleeps longer than the heartbeat interval causes at
        # least one `extend_visibility` call on its message.
        consumer = InMemoryMessageConsumer()
        consumer.enqueue(_event("SLOW.v1"))

        # Track extend_visibility calls on the message that was enqueued.
        extensions: list[int] = []

        # Patch the in-memory message's extend_visibility to record calls.
        original_extend = InMemoryMessage.extend_visibility

        async def capturing_extend(self, seconds: int) -> None:
            extensions.append(seconds)
            await original_extend(self, seconds)

        InMemoryMessage.extend_visibility = capturing_extend  # type: ignore[method-assign]

        try:

            async def handler(event: DomainEvent, ctx: dict) -> None:
                # Sleep long enough for at least one heartbeat tick.
                await asyncio.sleep(0.05)

            router = EventRouter()
            router.on("SLOW.v1", handler)

            worker = EventBusWorker(
                consumer=consumer,
                router=router,
                context={},
                worker_name="test_worker",
                use_heartbeat=True,
                heartbeat_interval=0,  # fire almost immediately
                heartbeat_extension=30,
                max_concurrency=1,
                max_messages_per_poll=1,
                wait_seconds=0,
            )

            await _run_one_loop(worker)
        finally:
            InMemoryMessage.extend_visibility = original_extend  # type: ignore[method-assign]

        assert extensions  # at least one heartbeat tick fired
        assert all(seconds == 30 for seconds in extensions)


class TestDrain:
    """`_drain()` handles the edge case where `run()` exits with tasks still in
    `self._in_flight` — e.g. an exception bubbles out of the poll path before
    `gather` completes. Tested directly rather than via the full run loop.
    """

    async def test_drain_no_op_when_empty(self) -> None:
        worker = EventBusWorker(
            consumer=InMemoryMessageConsumer(),
            router=EventRouter(),
            context={},
            worker_name="test_worker",
            use_heartbeat=False,
            max_concurrency=1,
            max_messages_per_poll=1,
            wait_seconds=0,
            drain_timeout=0,
        )
        # No tasks in-flight → drain returns without touching anything.
        await worker._drain()  # noqa: SLF001

    async def test_drain_cancels_pending_tasks_past_timeout(self) -> None:
        cancel_observed = asyncio.Event()

        async def never_finishes() -> None:
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancel_observed.set()
                raise

        worker = EventBusWorker(
            consumer=InMemoryMessageConsumer(),
            router=EventRouter(),
            context={},
            worker_name="test_worker",
            use_heartbeat=False,
            max_concurrency=1,
            max_messages_per_poll=1,
            wait_seconds=0,
            drain_timeout=0,  # cancel immediately
        )
        worker._in_flight = {asyncio.create_task(never_finishes())}  # noqa: SLF001

        await worker._drain()  # noqa: SLF001

        assert cancel_observed.is_set()

    async def test_drain_awaits_tasks_that_finish_within_timeout(self) -> None:
        completed = asyncio.Event()

        async def finishes_quickly() -> None:
            await asyncio.sleep(0)
            completed.set()

        worker = EventBusWorker(
            consumer=InMemoryMessageConsumer(),
            router=EventRouter(),
            context={},
            worker_name="test_worker",
            use_heartbeat=False,
            max_concurrency=1,
            max_messages_per_poll=1,
            wait_seconds=0,
            drain_timeout=5,  # plenty of time
        )
        worker._in_flight = {asyncio.create_task(finishes_quickly())}  # noqa: SLF001

        await worker._drain()  # noqa: SLF001

        assert completed.is_set()
