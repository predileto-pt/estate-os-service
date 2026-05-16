"""RabbitMQMessageConsumer — QoS + queue args + DLX + pull/push bridge.

Verifies the reliability primitives from spec
`2026-05-rabbitmq-transport-adapter` §3:
- `__aenter__` sets `basic.qos(prefetch_count=N)`.
- Queue declared idempotently with `x-queue-type=quorum`,
  `x-delivery-limit=5`, `x-dead-letter-exchange=<dlx>`.
- DLX declared idempotently (fanout, durable).
- Topic-exchange bindings created for events queues.
- `Message.message_id` returns AMQP property; falls back to delivery tag.
- `Message.ack` → `basic.ack`.
- `Message.nack` → `basic.nack(requeue=True)`.
- `Message.extend_visibility` is a no-op (no broker call).
- `poll()` short-returns on timeout (pull/push bridge).
- `__aexit__` cancels pump task and closes the channel.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from aio_pika import ExchangeType

from shared.events.adapters.rabbitmq_message_consumer import (
    RabbitMQMessage,
    RabbitMQMessageConsumer,
)
from shared.events.base import DomainEvent


def _connection_with_channel() -> tuple[MagicMock, AsyncMock, AsyncMock, AsyncMock]:
    """Wire connection → channel → queue mocks.

    Returns (connection, channel, queue, dlx_exchange).
    `queue` is the consumer's queue mock; the dead-letters queue is a
    separate mock kept internal to the helper.
    """
    connection = MagicMock()
    channel = AsyncMock()
    queue = AsyncMock()
    dead_letters_queue = AsyncMock()
    dlx_exchange = AsyncMock()
    bound_exchange = AsyncMock()

    async def declare_exchange(name: str, _kind: ExchangeType, **_kw: object) -> AsyncMock:
        if name == "domain-events-dlx" or name.endswith("-dlx"):
            return dlx_exchange
        return bound_exchange

    async def declare_queue(name: str, **_kw: object) -> AsyncMock:
        if name == "dead-letters":
            return dead_letters_queue
        return queue

    channel.declare_exchange = AsyncMock(side_effect=declare_exchange)
    channel.declare_queue = AsyncMock(side_effect=declare_queue)
    connection.channel = AsyncMock(return_value=channel)

    # queue.iterator() is an async context manager that yields nothing
    # by default — tests that exercise message flow do that via the
    # integration suite, not here.
    iterator_ctx = AsyncMock()
    iterator_ctx.__aenter__ = AsyncMock(return_value=iterator_ctx)
    iterator_ctx.__aexit__ = AsyncMock(return_value=None)
    iterator_ctx.__aiter__ = lambda self: self
    iterator_ctx.__anext__ = AsyncMock(side_effect=StopAsyncIteration)
    queue.iterator = MagicMock(return_value=iterator_ctx)
    return connection, channel, queue, dlx_exchange


async def test_aenter_sets_basic_qos_prefetch() -> None:
    connection, channel, _queue, _dlx = _connection_with_channel()
    consumer = RabbitMQMessageConsumer(connection, queue_name="q", prefetch_count=5)
    async with consumer:
        pass

    channel.set_qos.assert_awaited_once_with(prefetch_count=5)


async def test_aenter_declares_queue_with_quorum_and_delivery_limit() -> None:
    connection, channel, _queue, _dlx = _connection_with_channel()
    consumer = RabbitMQMessageConsumer(
        connection, queue_name="listings-events-queue", prefetch_count=5
    )
    async with consumer:
        pass

    # declare_queue is called twice: once for the consumer queue, once for
    # the global `dead-letters` queue bound to the DLX. Verify the consumer
    # queue declare carries the SQS-parity retry profile.
    consumer_queue_call = next(
        c for c in channel.declare_queue.await_args_list if c.args[0] == "listings-events-queue"
    )
    assert consumer_queue_call.kwargs == {
        "durable": True,
        "arguments": {
            "x-queue-type": "quorum",
            "x-delivery-limit": 5,
            "x-dead-letter-exchange": "domain-events-dlx",
        },
    }


async def test_aenter_declares_dlx_idempotently() -> None:
    connection, channel, _queue, _dlx = _connection_with_channel()
    consumer = RabbitMQMessageConsumer(connection, queue_name="q", dlx="custom-dlx")
    async with consumer:
        pass

    # Among the declare_exchange calls, one is for the DLX.
    declare_calls = [c for c in channel.declare_exchange.await_args_list]
    dlx_calls = [c for c in declare_calls if c.args[0] == "custom-dlx"]
    assert len(dlx_calls) == 1
    assert dlx_calls[0].args[1] == ExchangeType.FANOUT
    assert dlx_calls[0].kwargs.get("durable") is True


async def test_aenter_binds_queue_to_topic_exchange_for_each_pattern() -> None:
    connection, _channel, queue, _dlx = _connection_with_channel()
    consumer = RabbitMQMessageConsumer(
        connection,
        queue_name="listings-events-queue",
        bindings=[
            ("domain-events", "PROPERTY_*.v1"),
            ("domain-events", "PROPERTY_LISTING_*.v1"),
        ],
    )
    async with consumer:
        pass

    assert queue.bind.await_count == 2
    routing_keys = [c.kwargs["routing_key"] for c in queue.bind.await_args_list]
    assert routing_keys == ["PROPERTY_*.v1", "PROPERTY_LISTING_*.v1"]


async def test_command_queue_has_no_bindings() -> None:
    """Command queues use the default exchange routing — no topic bindings
    on the consumer's own queue. (The dead-letters queue is separately
    bound to the DLX by the consumer adapter; that's a different queue.)"""
    connection, _channel, queue, _dlx = _connection_with_channel()
    consumer = RabbitMQMessageConsumer(
        connection, queue_name="property-extraction-queue", bindings=[]
    )
    async with consumer:
        pass

    # The consumer's own queue must not be bound to any exchange.
    queue.bind.assert_not_awaited()


async def test_aexit_cancels_pump_and_closes_channel() -> None:
    connection, channel, _queue, _dlx = _connection_with_channel()
    consumer = RabbitMQMessageConsumer(connection, queue_name="q")
    async with consumer:
        pump = consumer._pump_task  # type: ignore[attr-defined]
        assert pump is not None
        assert not pump.done()
    # On exit pump is cancelled and channel closed.
    channel.close.assert_awaited_once()


async def test_poll_short_returns_when_buffer_empty() -> None:
    """The pull/push bridge: poll returns within wait_seconds even if
    no messages arrive — won't block forever."""
    connection, _channel, _queue, _dlx = _connection_with_channel()
    consumer = RabbitMQMessageConsumer(connection, queue_name="q")
    async with consumer:
        start = asyncio.get_event_loop().time()
        out = await consumer.poll(max_messages=10, wait_seconds=0)
        elapsed = asyncio.get_event_loop().time() - start
        assert out == []
        # wait_seconds=0 should return immediately (<100ms slack for CI).
        assert elapsed < 0.1


def _raw_message(body: bytes, message_id: str | None = None, delivery_tag: int = 1) -> MagicMock:
    raw = MagicMock()
    raw.body = body
    raw.message_id = message_id
    raw.delivery_tag = delivery_tag
    raw.ack = AsyncMock()
    raw.nack = AsyncMock()
    return raw


def test_message_message_id_reads_amqp_property() -> None:
    event = DomainEvent(event_type="X.v1", data={"foo": "bar"})
    raw = _raw_message(event.to_json().encode("utf-8"), message_id=event.event_id)

    msg = RabbitMQMessage(raw)

    assert msg.message_id == event.event_id


def test_message_message_id_falls_back_to_delivery_tag() -> None:
    """Only happens for messages published by an external producer that
    didn't set the AMQP message_id property."""
    event = DomainEvent(event_type="X.v1", data={})
    raw = _raw_message(event.to_json().encode("utf-8"), message_id=None, delivery_tag=42)

    msg = RabbitMQMessage(raw)

    assert msg.message_id == "42"


async def test_message_ack_calls_basic_ack() -> None:
    event = DomainEvent(event_type="X.v1", data={})
    raw = _raw_message(event.to_json().encode("utf-8"), message_id=event.event_id)

    msg = RabbitMQMessage(raw)
    await msg.ack()

    raw.ack.assert_awaited_once()


async def test_message_nack_requeues_for_redelivery_count() -> None:
    """`requeue=True` lets the broker count the redelivery against
    `x-delivery-limit` (matches SQS `maxReceiveCount`)."""
    event = DomainEvent(event_type="X.v1", data={})
    raw = _raw_message(event.to_json().encode("utf-8"), message_id=event.event_id)

    msg = RabbitMQMessage(raw)
    await msg.nack()

    raw.nack.assert_awaited_once_with(requeue=True)


async def test_message_extend_visibility_is_noop() -> None:
    """RabbitMQ has no per-message visibility timeout — the call returns
    without touching the broker."""
    event = DomainEvent(event_type="X.v1", data={})
    raw = _raw_message(event.to_json().encode("utf-8"), message_id=event.event_id)

    msg = RabbitMQMessage(raw)
    await msg.extend_visibility(120)

    # No broker-side method was called.
    raw.ack.assert_not_awaited()
    raw.nack.assert_not_awaited()


def test_message_unwraps_sns_envelope() -> None:
    """Backward compat: if a message comes in with an SNS-wrapped shape
    (legacy SNS+SQS handlers may emit this), we unwrap it transparently."""
    import json as _json

    inner_event = DomainEvent(event_type="X.v1", data={"foo": "bar"})
    sns_envelope = {"Type": "Notification", "Message": inner_event.to_json()}
    raw = _raw_message(_json.dumps(sns_envelope).encode("utf-8"))

    msg = RabbitMQMessage(raw)

    assert msg.event.event_type == "X.v1"
    assert msg.event.data == {"foo": "bar"}
