"""RabbitMQ integration — `basic.qos(prefetch_count=N)` enforces the cap.

Preloads many messages on a queue. Verifies that the consumer's internal
buffer never holds more than `prefetch_count` unacked messages at a time.
Prevents the mass-redelivery storm scenario (broker push-dumping every
unacked message on reconnect).
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


async def _cleanup(
    connection: aio_pika.abc.AbstractRobustConnection, queue: str, exchange: str
) -> None:
    async with connection.channel() as channel:
        try:
            await channel.queue_delete(queue)
        except Exception:
            pass
        try:
            await channel.exchange_delete(exchange)
        except Exception:
            pass


async def test_prefetch_caps_unacked_messages() -> None:
    suffix = uuid.uuid4().hex[:8]
    exchange_name = f"test-prefetch-{suffix}"
    queue_name = f"test-prefetch-queue-{suffix}"
    prefetch_count = 3
    total_messages = 20

    connection = await aio_pika.connect_robust(RABBITMQ_URL, heartbeat=30)
    try:
        publisher = RabbitMQEventPublisher(connection, exchange=exchange_name)
        consumer = RabbitMQMessageConsumer(
            connection=connection,
            queue_name=queue_name,
            bindings=[(exchange_name, "TEST_PREFETCH.v1")],
            prefetch_count=prefetch_count,
            dlx="domain-events-dlx",
        )

        async with consumer:
            # Preload all messages BEFORE consuming.
            for i in range(total_messages):
                await publisher.publish(
                    DomainEvent(event_type="TEST_PREFETCH.v1", data={"i": i})
                )

            # The broker delivers at most prefetch_count unacked messages
            # at a time. Our internal buffer is bounded at prefetch_count.
            # A poll without acks should return at most prefetch_count.
            messages = await consumer.poll(
                max_messages=total_messages, wait_seconds=2
            )
            assert len(messages) <= prefetch_count, (
                f"expected at most {prefetch_count} unacked messages, got {len(messages)}"
            )

            # Drain — ack each, then poll for the next batch.
            consumed = len(messages)
            for msg in messages:
                await msg.ack()

            while consumed < total_messages:
                batch = await consumer.poll(
                    max_messages=total_messages - consumed, wait_seconds=2
                )
                if not batch:
                    break
                assert len(batch) <= prefetch_count
                for msg in batch:
                    await msg.ack()
                consumed += len(batch)

            assert consumed == total_messages

        await _cleanup(connection, queue_name, exchange_name)
    finally:
        await connection.close()
