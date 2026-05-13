"""RabbitMQ integration — publish → bound queue → consume → ack.

Happy-path round-trip via the dev compose's rabbitmq service. Gated on
RABBITMQ_URL being set (won't run in CI environments without a live broker).
"""

import os
import uuid

import aio_pika
import pytest

from shared.events.adapters.rabbitmq_event_publisher import RabbitMQEventPublisher
from shared.events.adapters.rabbitmq_message_consumer import RabbitMQMessageConsumer
from shared.events.base import DomainEvent

RABBITMQ_URL = os.environ.get("RABBITMQ_URL")

pytestmark = pytest.mark.skipif(
    not RABBITMQ_URL, reason="RABBITMQ_URL not set — RabbitMQ broker not reachable"
)


async def _cleanup(connection: aio_pika.abc.AbstractRobustConnection, queue: str, exchange: str) -> None:
    async with connection.channel() as channel:
        try:
            await channel.queue_delete(queue)
        except Exception:
            pass
        try:
            await channel.exchange_delete(exchange)
        except Exception:
            pass


async def test_publish_to_bound_queue_consume_and_ack() -> None:
    suffix = uuid.uuid4().hex[:8]
    exchange_name = f"test-events-{suffix}"
    queue_name = f"test-events-queue-{suffix}"

    connection = await aio_pika.connect_robust(RABBITMQ_URL, heartbeat=30)
    try:
        publisher = RabbitMQEventPublisher(connection, exchange=exchange_name)
        consumer = RabbitMQMessageConsumer(
            connection=connection,
            queue_name=queue_name,
            bindings=[(exchange_name, "TEST_EVENT.v1")],
            prefetch_count=5,
            dlx="domain-events-dlx",
        )

        async with consumer:
            event = DomainEvent(event_type="TEST_EVENT.v1", data={"foo": "bar"})
            await publisher.publish(event)

            messages = await consumer.poll(max_messages=1, wait_seconds=5)
            assert len(messages) == 1
            received = messages[0]
            assert received.event.event_type == "TEST_EVENT.v1"
            assert received.event.data == {"foo": "bar"}
            assert received.message_id == event.event_id
            await received.ack()

        await _cleanup(connection, queue_name, exchange_name)
    finally:
        await connection.close()
