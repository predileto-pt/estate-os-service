"""RabbitMQ integration — messages survive broker restart.

Publish with `delivery_mode=PERSISTENT` (=2) to a durable queue, restart
the rabbitmq container, then consume — message is still there.

Requires `docker compose` to be available on PATH and the dev compose
to be running locally with a `rabbitmq` service.
"""

import asyncio
import os
import shutil
import subprocess
import uuid

import aio_pika
import pytest

from shared.events.adapters.rabbitmq_event_publisher import RabbitMQEventPublisher
from shared.events.adapters.rabbitmq_message_consumer import RabbitMQMessageConsumer
from shared.events.base import DomainEvent

RABBITMQ_URL = os.environ.get("RABBITMQ_URL")

pytestmark = pytest.mark.skipif(
    not RABBITMQ_URL or shutil.which("docker") is None,
    reason="needs RABBITMQ_URL + docker on PATH for container restart",
)


async def _wait_for_broker(url: str, timeout: float = 30.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    last_exc: Exception | None = None
    while asyncio.get_event_loop().time() < deadline:
        try:
            conn = await aio_pika.connect_robust(url, heartbeat=30, timeout=2)
            await conn.close()
            return
        except Exception as exc:
            last_exc = exc
            await asyncio.sleep(1)
    raise RuntimeError(f"broker not reachable within {timeout}s: {last_exc}")


async def test_persistent_message_survives_broker_restart() -> None:
    suffix = uuid.uuid4().hex[:8]
    exchange_name = f"test-persist-{suffix}"
    queue_name = f"test-persist-queue-{suffix}"

    connection = await aio_pika.connect_robust(RABBITMQ_URL, heartbeat=30)
    try:
        # Pre-declare the queue (idempotent) so it's durable BEFORE we
        # publish. Then publish and close cleanly.
        consumer = RabbitMQMessageConsumer(
            connection=connection,
            queue_name=queue_name,
            bindings=[(exchange_name, "TEST_PERSIST.v1")],
            prefetch_count=5,
            dlx="domain-events-dlx",
        )
        async with consumer:
            pass  # just to run __aenter__ (declare + bind)

        publisher = RabbitMQEventPublisher(connection, exchange=exchange_name)
        event = DomainEvent(event_type="TEST_PERSIST.v1", data={"survives": True})
        await publisher.publish(event)
    finally:
        await connection.close()

    # Restart the broker. New connection after restart.
    subprocess.run(
        ["docker", "compose", "restart", "rabbitmq"], check=True, capture_output=True
    )
    await _wait_for_broker(RABBITMQ_URL)

    connection = await aio_pika.connect_robust(RABBITMQ_URL, heartbeat=30)
    try:
        consumer = RabbitMQMessageConsumer(
            connection=connection,
            queue_name=queue_name,
            bindings=[(exchange_name, "TEST_PERSIST.v1")],
            prefetch_count=5,
            dlx="domain-events-dlx",
        )
        async with consumer:
            messages = await consumer.poll(max_messages=1, wait_seconds=10)
            assert len(messages) == 1
            assert messages[0].event.data == {"survives": True}
            await messages[0].ack()

        async with connection.channel() as cleanup:
            try:
                await cleanup.queue_delete(queue_name)
            except Exception:
                pass
            try:
                await cleanup.exchange_delete(exchange_name)
            except Exception:
                pass
    finally:
        await connection.close()
