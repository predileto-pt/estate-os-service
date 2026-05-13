"""RabbitMQ integration — retry budget = 5 via `x-delivery-limit`.

Matches SQS `maxReceiveCount=5`. After the 5th nack(requeue=true) on
the same message, the broker auto-routes to the DLX. The
`dead-letters` queue receives it with `x-death` headers reflecting the
redelivery count.
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
    connection: aio_pika.abc.AbstractRobustConnection,
    queue: str,
    exchange: str,
    dlx: str,
    dead_letters: str,
) -> None:
    async with connection.channel() as channel:
        for name in [queue, dead_letters]:
            try:
                await channel.queue_delete(name)
            except Exception:
                pass
        for name in [exchange, dlx]:
            try:
                await channel.exchange_delete(name)
            except Exception:
                pass


async def test_nack_5_times_routes_to_dlx() -> None:
    suffix = uuid.uuid4().hex[:8]
    exchange_name = f"test-events-{suffix}"
    queue_name = f"test-retry-queue-{suffix}"
    dlx_name = f"test-dlx-{suffix}"
    dead_letters_name = f"test-dead-letters-{suffix}"

    connection = await aio_pika.connect_robust(RABBITMQ_URL, heartbeat=30)
    try:
        # Pre-declare the dead-letters queue + bind to the DLX so we can
        # consume failures.
        async with connection.channel() as setup:
            await setup.declare_exchange(
                dlx_name, aio_pika.ExchangeType.FANOUT, durable=True
            )
            dl_queue = await setup.declare_queue(dead_letters_name, durable=True)
            dlx = await setup.get_exchange(dlx_name)
            await dl_queue.bind(dlx)

        publisher = RabbitMQEventPublisher(connection, exchange=exchange_name)
        consumer = RabbitMQMessageConsumer(
            connection=connection,
            queue_name=queue_name,
            bindings=[(exchange_name, "TEST_RETRY.v1")],
            prefetch_count=1,
            dlx=dlx_name,
        )

        async with consumer:
            event = DomainEvent(event_type="TEST_RETRY.v1", data={"i": 1})
            await publisher.publish(event)

            # Nack repeatedly until the broker stops redelivering — proves
            # the redelivery loop is bounded. `x-delivery-limit=5` counts
            # redeliveries (not total deliveries), so we expect 6 attempts
            # total before DLX-routing kicks in (1 initial + 5 redeliveries).
            nack_count = 0
            while nack_count < 10:  # safety cap to bound test time
                messages = await consumer.poll(max_messages=1, wait_seconds=3)
                if not messages:
                    break
                await messages[0].nack()
                nack_count += 1

            assert nack_count <= 6, (
                f"expected ≤6 nacks before DLX routing, got {nack_count} "
                "(x-delivery-limit=5 means 5 redeliveries after initial)"
            )
            assert nack_count >= 5, (
                f"expected ≥5 nacks to exercise the limit, got {nack_count}"
            )

        # The message now lives in dead_letters_name.
        async with connection.channel() as inspect:
            dead_queue = await inspect.declare_queue(
                dead_letters_name, durable=True, passive=True
            )
            incoming = await dead_queue.get(no_ack=True, fail=False)
            assert incoming is not None, "expected message in dead-letters queue"
            # x-death header chain shows the redelivery count.
            x_death = incoming.headers.get("x-death") if incoming.headers else None
            assert x_death is not None, "expected x-death header"

        await _cleanup(connection, queue_name, exchange_name, dlx_name, dead_letters_name)
    finally:
        await connection.close()
