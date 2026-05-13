"""Command-queue worker smoke + DLQ + expected-exception behaviour.

Three acceptance criteria from the foundation spec:

1. **Worker smoke** — publish a canonical `DomainEvent` via
   `SQSCommandPublisher.send()`, run the shared `EventBusWorker` with a
   handler, observe the handler is invoked and the message is ack'd.
2. **DLQ routing** — handler always raises an unhandled `RuntimeError`.
   After `maxReceiveCount` redeliveries, the message lands in the DLQ
   and the source queue is empty. No silent drop.
3. **Expected exception caught inside handler** — an expected business
   exception (e.g. `InvalidJobTransitionError`) is caught and logged by
   the handler, which returns normally. The worker ack's after ONE
   attempt; the message does NOT redeliver.

Tests use the shared `EventBusWorker` with a short-poll consumer and a
redrive policy set to `maxReceiveCount=2` + `VisibilityTimeout=1s` so
the DLQ flow completes in a few seconds instead of minutes.
"""

import asyncio
import json
from collections.abc import Callable

import aioboto3
import pytest

from shared.events.adapters.sqs_command_publisher import SQSCommandPublisher
from shared.events.adapters.sqs_message_consumer import SQSMessageConsumer
from shared.events.base import DomainEvent
from shared.events.router import EventRouter
from shared.events.worker import EventBusWorker

EVENT_TYPE = "TEST_COMMAND.v1"


def _create_queue_with_redrive(
    sqs_client, name: str, dlq_name: str, max_receive_count: int = 2
) -> tuple[str, str]:
    dlq_resp = sqs_client.create_queue(QueueName=dlq_name)
    dlq_url = dlq_resp["QueueUrl"]
    dlq_attrs = sqs_client.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])
    dlq_arn = dlq_attrs["Attributes"]["QueueArn"]

    redrive = {"deadLetterTargetArn": dlq_arn, "maxReceiveCount": str(max_receive_count)}
    queue_resp = sqs_client.create_queue(
        QueueName=name,
        Attributes={
            "VisibilityTimeout": "1",
            "RedrivePolicy": json.dumps(redrive),
        },
    )
    return queue_resp["QueueUrl"], dlq_url


async def _run_worker_until(
    worker: EventBusWorker, condition: Callable[[], bool], timeout: float = 20.0
) -> None:
    """Drive the worker's run loop until `condition()` is True or `timeout` s elapse."""
    task = asyncio.create_task(worker.run())
    try:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if condition():
                break
            await asyncio.sleep(0.15)
    finally:
        worker._running = False  # noqa: SLF001
        try:
            await asyncio.wait_for(task, timeout=5)
        except TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def _queue_depth(sqs_client, queue_url: str) -> int:
    resp = sqs_client.get_queue_attributes(
        QueueUrl=queue_url,
        AttributeNames=["ApproximateNumberOfMessages"],
    )
    return int(resp["Attributes"]["ApproximateNumberOfMessages"])


async def test_smoke_happy_path(localstack_url, aws_credentials, sqs_client):
    """Handler receives event, worker ack's, queue is empty."""
    queue_url, _dlq_url = _create_queue_with_redrive(
        sqs_client, "smoke-happy-queue", "smoke-happy-dlq"
    )

    session = aioboto3.Session(**aws_credentials)
    publisher = SQSCommandPublisher(session=session, endpoint_url=localstack_url)

    received: list[DomainEvent] = []

    async def handler(event: DomainEvent, ctx) -> None:
        received.append(event)

    router = EventRouter()
    router.on(EVENT_TYPE, handler)

    consumer = SQSMessageConsumer(session=session, queue_url=queue_url, endpoint_url=localstack_url)
    worker = EventBusWorker(
        consumer=consumer,
        router=router,
        context={},
        worker_name="smoke_worker",
        use_heartbeat=False,
        max_concurrency=1,
        max_messages_per_poll=1,
        wait_seconds=0,
    )

    await publisher.send(queue_url, DomainEvent(event_type=EVENT_TYPE, data={"job_id": "smoke-1"}))
    await _run_worker_until(worker, lambda: len(received) >= 1)

    assert len(received) == 1
    assert received[0].data == {"job_id": "smoke-1"}
    assert _queue_depth(sqs_client, queue_url) == 0


async def test_dlq_routes_after_max_receive_count(localstack_url, aws_credentials, sqs_client):
    """Handler always raises → message lands in DLQ after maxReceiveCount=2 attempts."""
    queue_url, dlq_url = _create_queue_with_redrive(
        sqs_client, "dlq-test-queue", "dlq-test-dlq", max_receive_count=2
    )

    session = aioboto3.Session(**aws_credentials)
    publisher = SQSCommandPublisher(session=session, endpoint_url=localstack_url)

    attempts = 0

    async def always_raises(event: DomainEvent, ctx) -> None:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("intentional failure")

    router = EventRouter()
    router.on(EVENT_TYPE, always_raises)

    consumer = SQSMessageConsumer(session=session, queue_url=queue_url, endpoint_url=localstack_url)
    worker = EventBusWorker(
        consumer=consumer,
        router=router,
        context={},
        worker_name="dlq_test_worker",
        use_heartbeat=False,
        max_concurrency=1,
        max_messages_per_poll=1,
        wait_seconds=0,
    )

    await publisher.send(queue_url, DomainEvent(event_type=EVENT_TYPE, data={"job_id": "dlq-1"}))
    await _run_worker_until(worker, lambda: _queue_depth(sqs_client, dlq_url) >= 1, timeout=30.0)

    # Source queue drained — redrive moved the message.
    assert _queue_depth(sqs_client, queue_url) == 0
    # DLQ has it.
    assert _queue_depth(sqs_client, dlq_url) == 1
    # Handler was invoked maxReceiveCount times (exactly 2 with this redrive).
    assert attempts == 2


async def test_expected_exception_caught_in_handler_acks_after_one_attempt(
    localstack_url, aws_credentials, sqs_client
):
    """Proves the DB-status path still works. Handlers that catch expected
    business exceptions (InvalidJobTransitionError, etc.) return normally —
    the worker treats that as success and ack's. No redelivery.
    """
    queue_url, dlq_url = _create_queue_with_redrive(
        sqs_client, "caught-test-queue", "caught-test-dlq", max_receive_count=2
    )

    session = aioboto3.Session(**aws_credentials)
    publisher = SQSCommandPublisher(session=session, endpoint_url=localstack_url)

    attempts = 0

    class _ExpectedError(Exception):
        """Stand-in for InvalidJobTransitionError / ExtractionJobNotFoundError."""

    async def handler(event: DomainEvent, ctx) -> None:
        nonlocal attempts
        attempts += 1
        try:
            # Simulate a use-case raising an expected exception.
            raise _ExpectedError("job in terminal state, skipping")
        except _ExpectedError:
            # Handler CATCHES and returns normally — this is the pattern
            # every real handler uses for expected business exceptions.
            return

    router = EventRouter()
    router.on(EVENT_TYPE, handler)

    consumer = SQSMessageConsumer(session=session, queue_url=queue_url, endpoint_url=localstack_url)
    worker = EventBusWorker(
        consumer=consumer,
        router=router,
        context={},
        worker_name="caught_test_worker",
        use_heartbeat=False,
        max_concurrency=1,
        max_messages_per_poll=1,
        wait_seconds=0,
    )

    await publisher.send(queue_url, DomainEvent(event_type=EVENT_TYPE, data={"job_id": "caught-1"}))
    await _run_worker_until(
        worker, lambda: attempts >= 1 and _queue_depth(sqs_client, queue_url) == 0
    )

    # Handler invoked once; redelivery didn't happen.
    assert attempts == 1
    # Source queue is empty (ack'd).
    assert _queue_depth(sqs_client, queue_url) == 0
    # DLQ is empty.
    assert _queue_depth(sqs_client, dlq_url) == 0


@pytest.fixture
def _not_used() -> None:
    # pytest-asyncio runs these as coroutines via `asyncio_mode = "auto"`.
    return None
