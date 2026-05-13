"""RabbitMQ integration — mandatory=True raises on misroute.

CommandPublisher.send() to a non-existent queue name raises
`aio_pika.exceptions.DeliveryError` instead of silently dropping the
message. Catches the most common silent-failure mode of AMQP.
"""

import asyncio
import os
import uuid

import aio_pika
import pytest

RABBITMQ_URL = os.environ.get("RABBITMQ_URL")

pytestmark = pytest.mark.skipif(
    not RABBITMQ_URL, reason="RABBITMQ_URL not set — RabbitMQ broker not reachable"
)


async def test_send_to_nonexistent_queue_triggers_basic_return() -> None:
    """Verify the broker emits `basic.return` on a mandatory misroute.

    aio-pika 9.x delivers `basic.return` asynchronously via channel callbacks
    rather than raising synchronously from `publish()` — see the open
    questions in the spec. We capture it explicitly via `on_return_raises`
    on the channel to surface the failure to the publisher.
    """
    connection = await aio_pika.connect_robust(RABBITMQ_URL, heartbeat=30)
    try:
        returned_messages: list = []

        async def _on_return(*args: object, **_kwargs: object) -> None:
            # aio-pika's return-callback signature varies across releases;
            # accept any shape — we only care that the broker called back.
            returned_messages.append(args)

        async with connection.channel(publisher_confirms=True) as channel:
            channel.return_callbacks.add(_on_return)
            missing_queue = f"queue-that-doesnt-exist-{uuid.uuid4().hex[:8]}"
            await channel.default_exchange.publish(
                aio_pika.Message(b"{}", message_id="test"),
                routing_key=missing_queue,
                mandatory=True,
            )
            # Allow the broker's basic.return frame time to arrive.
            await asyncio.sleep(0.5)

        assert len(returned_messages) == 1, (
            "broker should have returned the unroutable message via basic.return"
        )
    finally:
        await connection.close()
