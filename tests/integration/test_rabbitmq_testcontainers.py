"""RabbitMQ adapter end-to-end via testcontainers — success + failure.

Self-contained: spins up a fresh RabbitMQ broker per test session via
`testcontainers.rabbitmq`. No need for `docker compose up` first, no
shared state with the dev broker — works in CI as long as Docker is
available.

Two scenarios, mapping to the spec's reliability claims:

1. **Success path** — publish → bound queue → consume → ack. Confirms
   that publisher confirms + persistent messages + topic-exchange
   routing + the pull/push buffer cooperate end-to-end on a fresh broker.

2. **Failure path** — handler always fails → 5 nacks → message lands
   in `dead-letters` via the DLX. Confirms the `x-delivery-limit=5` +
   quorum-queue + global-DLX retry budget matches SQS `maxReceiveCount=5`.
"""

from __future__ import annotations

import asyncio
import shutil
import uuid
from collections.abc import Iterator

import aio_pika
import pytest

from shared.events.adapters.rabbitmq_event_publisher import RabbitMQEventPublisher
from shared.events.adapters.rabbitmq_message_consumer import RabbitMQMessageConsumer
from shared.events.base import DomainEvent

pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="testcontainers needs Docker on PATH",
)


@pytest.fixture(scope="module")
def rabbitmq_url() -> Iterator[str]:
    """Spin up a fresh RabbitMQ broker for this test module."""
    from testcontainers.rabbitmq import RabbitMqContainer

    with RabbitMqContainer("rabbitmq:3.13-management-alpine") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(5672)
        # testcontainers' RabbitMqContainer defaults to guest/guest.
        yield f"amqp://guest:guest@{host}:{port}/"


@pytest.fixture
def names() -> dict[str, str]:
    """Unique exchange/queue names per test to avoid cross-test bleed."""
    suffix = uuid.uuid4().hex[:8]
    return {
        "exchange": f"test-events-{suffix}",
        "queue": f"test-queue-{suffix}",
        "routing_key": "TEST_EVENT.v1",
    }


async def test_success_path_publish_consume_ack(
    rabbitmq_url: str, names: dict[str, str]
) -> None:
    """A published event reaches its bound queue, the consumer receives
    it, and `ack` removes it from the broker. End-to-end happy path."""
    connection = await aio_pika.connect_robust(rabbitmq_url, heartbeat=30)
    try:
        publisher = RabbitMQEventPublisher(connection, exchange=names["exchange"])
        consumer = RabbitMQMessageConsumer(
            connection=connection,
            queue_name=names["queue"],
            bindings=[(names["exchange"], names["routing_key"])],
            prefetch_count=5,
            dlx="domain-events-dlx",
        )

        async with consumer:
            event = DomainEvent(
                event_type=names["routing_key"], data={"path": "success"}
            )
            await publisher.publish(event)

            messages = await consumer.poll(max_messages=1, wait_seconds=5)
            assert len(messages) == 1, "publisher → bound queue should deliver"
            received = messages[0]
            assert received.event.event_type == names["routing_key"]
            assert received.event.data == {"path": "success"}
            assert received.message_id == event.event_id
            await received.ack()

            # Post-ack, the queue should be drained — next poll empty.
            tail = await consumer.poll(max_messages=1, wait_seconds=1)
            assert tail == [], "ack should remove the message from the queue"
    finally:
        await connection.close()


async def test_failure_path_routes_to_dlx_after_retry_budget(
    rabbitmq_url: str, names: dict[str, str]
) -> None:
    """A handler that always raises → consumer nacks → broker requeues →
    after `x-delivery-limit=5` redeliveries, the broker auto-routes to
    the DLX. The `dead-letters` queue receives the message. Consumer
    never sees a 7th delivery."""
    connection = await aio_pika.connect_robust(rabbitmq_url, heartbeat=30)
    try:
        publisher = RabbitMQEventPublisher(connection, exchange=names["exchange"])
        consumer = RabbitMQMessageConsumer(
            connection=connection,
            queue_name=names["queue"],
            bindings=[(names["exchange"], names["routing_key"])],
            prefetch_count=1,
            dlx="domain-events-dlx",
        )

        async with consumer:
            event = DomainEvent(
                event_type=names["routing_key"], data={"path": "failure"}
            )
            await publisher.publish(event)

            # Simulate "handler always raises" by nacking every delivery.
            # Bound at 10 iterations to keep the test fast even if the
            # broker behaves differently than expected.
            nack_count = 0
            while nack_count < 10:
                messages = await consumer.poll(max_messages=1, wait_seconds=3)
                if not messages:
                    break
                await messages[0].nack()
                nack_count += 1

            # `x-delivery-limit=5` = 5 redeliveries + 1 initial = 6 nacks
            # before the broker DLX-routes. ≤6 is the SQS-parity bound.
            assert 5 <= nack_count <= 6, (
                f"expected ≤6 nacks before DLX routing, got {nack_count}"
            )

        # Allow the broker a moment to flush the DLX route.
        await asyncio.sleep(0.5)

        # The message should now be in the global `dead-letters` queue.
        async with connection.channel() as channel:
            dead_letters = await channel.declare_queue("dead-letters", durable=True)
            incoming = await dead_letters.get(no_ack=True, fail=False)
            assert incoming is not None, "message should be in dead-letters via DLX"
            assert incoming.headers is not None
            x_death = incoming.headers.get("x-death")
            assert x_death is not None, (
                "x-death header chain should record the redelivery count"
            )
    finally:
        await connection.close()
