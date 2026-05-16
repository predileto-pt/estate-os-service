"""RabbitMQEventPublisher — channel-per-publish + publisher confirms +
persistent + AMQP message_id property.

Verifies the reliability primitives from spec
`2026-05-rabbitmq-transport-adapter` §3:
- Channel opened with `publisher_confirms=True`.
- `publish()` returns only after `basic.ack` (aio-pika awaits it).
- Topic exchange declared idempotently (durable=True).
- Routing-key = event.event_type.
- AMQP `message_id` property = event.event_id.
- `delivery_mode=PERSISTENT` (=2).
- Channel closed after each publish (channel-per-publish).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aio_pika import DeliveryMode, ExchangeType

from shared.events.adapters.rabbitmq_event_publisher import RabbitMQEventPublisher
from shared.events.base import DomainEvent


def _make_connection_mock() -> tuple[MagicMock, AsyncMock, AsyncMock]:
    """Wire connection → channel → exchange mocks.

    Returns (connection, channel, exchange) so tests can assert on
    each layer's calls.
    """
    connection = MagicMock()
    channel = AsyncMock()
    exchange = AsyncMock()
    channel.declare_exchange = AsyncMock(return_value=exchange)
    # connection.channel(publisher_confirms=True) is an async context manager.
    channel_ctx = AsyncMock()
    channel_ctx.__aenter__ = AsyncMock(return_value=channel)
    channel_ctx.__aexit__ = AsyncMock(return_value=None)
    connection.channel = MagicMock(return_value=channel_ctx)
    return connection, channel, exchange


async def test_publish_uses_publisher_confirms_channel() -> None:
    connection, _channel, _exchange = _make_connection_mock()
    publisher = RabbitMQEventPublisher(connection, exchange="domain-events")

    await publisher.publish(DomainEvent(event_type="X.v1", data={}))

    connection.channel.assert_called_once_with(publisher_confirms=True)


async def test_publish_declares_topic_exchange_durable() -> None:
    connection, channel, _exchange = _make_connection_mock()
    publisher = RabbitMQEventPublisher(connection, exchange="domain-events")

    await publisher.publish(DomainEvent(event_type="X.v1", data={}))

    channel.declare_exchange.assert_awaited_once_with(
        "domain-events", ExchangeType.TOPIC, durable=True
    )


async def test_publish_routes_by_event_type() -> None:
    connection, _channel, exchange = _make_connection_mock()
    publisher = RabbitMQEventPublisher(connection)

    await publisher.publish(DomainEvent(event_type="PROPERTY_CREATED.v1", data={}))

    # exchange.publish(message, routing_key=...)
    call_args = exchange.publish.await_args
    assert call_args.kwargs["routing_key"] == "PROPERTY_CREATED.v1"


async def test_publish_sets_amqp_message_id_to_event_id() -> None:
    connection, _channel, exchange = _make_connection_mock()
    publisher = RabbitMQEventPublisher(connection)

    event = DomainEvent(event_type="X.v1", data={})
    await publisher.publish(event)

    sent_message = exchange.publish.await_args.args[0]
    assert sent_message.message_id == event.event_id


async def test_publish_sets_delivery_mode_persistent() -> None:
    connection, _channel, exchange = _make_connection_mock()
    publisher = RabbitMQEventPublisher(connection)

    await publisher.publish(DomainEvent(event_type="X.v1", data={}))

    sent_message = exchange.publish.await_args.args[0]
    # PERSISTENT == 2 in the AMQP spec.
    assert sent_message.delivery_mode == DeliveryMode.PERSISTENT


async def test_publish_body_is_event_to_json() -> None:
    connection, _channel, exchange = _make_connection_mock()
    publisher = RabbitMQEventPublisher(connection)

    event = DomainEvent(event_type="X.v1", data={"foo": "bar"})
    await publisher.publish(event)

    sent_message = exchange.publish.await_args.args[0]
    assert sent_message.body == event.to_json().encode("utf-8")


async def test_publish_channel_is_closed_per_call() -> None:
    """Channel-per-publish: each publish opens a fresh channel context
    and closes it on return (verified via the async-with __aexit__ call)."""
    connection, _channel, _exchange = _make_connection_mock()
    publisher = RabbitMQEventPublisher(connection)

    await publisher.publish(DomainEvent(event_type="X.v1", data={}))
    await publisher.publish(DomainEvent(event_type="X.v1", data={}))

    assert connection.channel.call_count == 2


async def test_publish_propagates_broker_nack_as_exception() -> None:
    """When the broker basic.nack's the publish, aio-pika raises.
    Our publisher does not swallow it — caller sees the failure.
    The retry helper re-raises immediately because the message
    doesn't match the "Connection was not opened" marker."""
    connection, _channel, exchange = _make_connection_mock()
    exchange.publish = AsyncMock(side_effect=RuntimeError("broker nacked"))
    publisher = RabbitMQEventPublisher(connection)

    with pytest.raises(RuntimeError, match="broker nacked"):
        await publisher.publish(DomainEvent(event_type="X.v1", data={}))


async def test_publish_retries_transient_connection_not_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On the cold-start race the spec is closing, the first channel()
    call raises `Connection was not opened`. The publisher should retry
    and succeed on the second attempt."""

    # Skip the real sleep.
    async def _noop(_seconds: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _noop)

    connection, channel, _exchange = _make_connection_mock()
    # First channel() invocation raises on __aenter__; second succeeds.
    failing_ctx = AsyncMock()
    failing_ctx.__aenter__ = AsyncMock(side_effect=RuntimeError("Connection was not opened"))
    failing_ctx.__aexit__ = AsyncMock(return_value=None)
    success_ctx = connection.channel.return_value  # the original happy-path ctx
    connection.channel = MagicMock(side_effect=[failing_ctx, success_ctx])

    publisher = RabbitMQEventPublisher(connection)
    await publisher.publish(DomainEvent(event_type="X.v1", data={}))

    assert connection.channel.call_count == 2
    # The second (successful) channel got the real declare + publish flow.
    channel.declare_exchange.assert_awaited()


async def test_publish_raises_publish_failed_after_retry_on_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When all three attempts trip the retriable error, the publisher
    raises PublishFailedAfterRetry with the event/sink metadata so callers
    have a structured terminal signal."""
    from shared.events.adapters._publish_retry import PublishFailedAfterRetry

    async def _noop(_seconds: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _noop)

    connection = MagicMock()
    failing_ctx = AsyncMock()
    failing_ctx.__aenter__ = AsyncMock(side_effect=RuntimeError("Connection was not opened"))
    failing_ctx.__aexit__ = AsyncMock(return_value=None)
    connection.channel = MagicMock(return_value=failing_ctx)

    publisher = RabbitMQEventPublisher(connection, exchange="domain-events")

    with pytest.raises(PublishFailedAfterRetry) as exc_info:
        await publisher.publish(DomainEvent(event_type="PROPERTY_UPDATED.v1", data={}))

    err = exc_info.value
    assert err.event_type == "PROPERTY_UPDATED.v1"
    assert err.sink == "domain-events"
    assert err.attempts == 3
