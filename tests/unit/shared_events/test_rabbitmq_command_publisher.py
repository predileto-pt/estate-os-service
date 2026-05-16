"""RabbitMQCommandPublisher — channel-per-send + publisher confirms +
mandatory + persistent.

Verifies the reliability primitives from spec
`2026-05-rabbitmq-transport-adapter` §3:
- Channel opened with `publisher_confirms=True`.
- Routes via default exchange with routing-key = queue_url.
- AMQP `message_id` property = event.event_id.
- `delivery_mode=PERSISTENT` (=2).
- `mandatory=True` so misroute raises (no silent drop).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aio_pika import DeliveryMode

from shared.events.adapters.rabbitmq_command_publisher import RabbitMQCommandPublisher
from shared.events.base import DomainEvent


def _make_connection_mock() -> tuple[MagicMock, AsyncMock, AsyncMock]:
    connection = MagicMock()
    channel = AsyncMock()
    default_exchange = AsyncMock()
    channel.default_exchange = default_exchange
    channel_ctx = AsyncMock()
    channel_ctx.__aenter__ = AsyncMock(return_value=channel)
    channel_ctx.__aexit__ = AsyncMock(return_value=None)
    connection.channel = MagicMock(return_value=channel_ctx)
    return connection, channel, default_exchange


async def test_send_uses_publisher_confirms_channel() -> None:
    connection, _channel, _default_exchange = _make_connection_mock()
    publisher = RabbitMQCommandPublisher(connection)

    await publisher.send("property-extraction-queue", DomainEvent(event_type="X.v1", data={}))

    connection.channel.assert_called_once_with(publisher_confirms=True)


async def test_send_routes_to_queue_name_on_default_exchange() -> None:
    connection, _channel, default_exchange = _make_connection_mock()
    publisher = RabbitMQCommandPublisher(connection)

    await publisher.send("property-extraction-queue", DomainEvent(event_type="X.v1", data={}))

    call_args = default_exchange.publish.await_args
    assert call_args.kwargs["routing_key"] == "property-extraction-queue"


async def test_send_sets_mandatory_flag() -> None:
    connection, _channel, default_exchange = _make_connection_mock()
    publisher = RabbitMQCommandPublisher(connection)

    await publisher.send("some-queue", DomainEvent(event_type="X.v1", data={}))

    assert default_exchange.publish.await_args.kwargs["mandatory"] is True


async def test_send_sets_amqp_message_id_to_event_id() -> None:
    connection, _channel, default_exchange = _make_connection_mock()
    publisher = RabbitMQCommandPublisher(connection)

    event = DomainEvent(event_type="X.v1", data={})
    await publisher.send("some-queue", event)

    sent_message = default_exchange.publish.await_args.args[0]
    assert sent_message.message_id == event.event_id


async def test_send_sets_delivery_mode_persistent() -> None:
    connection, _channel, default_exchange = _make_connection_mock()
    publisher = RabbitMQCommandPublisher(connection)

    await publisher.send("some-queue", DomainEvent(event_type="X.v1", data={}))

    sent_message = default_exchange.publish.await_args.args[0]
    assert sent_message.delivery_mode == DeliveryMode.PERSISTENT


async def test_send_propagates_mandatory_misroute_as_exception() -> None:
    """When no queue is bound to the routing key, aio-pika raises
    `DeliveryError`. The retry helper classifies DeliveryError as
    non-retriable and re-raises immediately (no retry)."""
    from aio_pika.exceptions import DeliveryError

    connection, _channel, default_exchange = _make_connection_mock()
    default_exchange.publish = AsyncMock(side_effect=DeliveryError([], "unroutable"))
    publisher = RabbitMQCommandPublisher(connection)

    with pytest.raises(DeliveryError):
        await publisher.send("missing-queue", DomainEvent(event_type="X.v1", data={}))
    # No retry — exactly one channel open.
    assert connection.channel.call_count == 1


async def test_send_retries_transient_connection_not_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Symmetric to the event publisher: cold-start race on a worker
    queue PATCH retries and succeeds."""

    async def _noop(_seconds: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _noop)

    connection, _channel, _default_exchange = _make_connection_mock()
    failing_ctx = AsyncMock()
    failing_ctx.__aenter__ = AsyncMock(side_effect=RuntimeError("Connection was not opened"))
    failing_ctx.__aexit__ = AsyncMock(return_value=None)
    success_ctx = connection.channel.return_value
    connection.channel = MagicMock(side_effect=[failing_ctx, success_ctx])

    publisher = RabbitMQCommandPublisher(connection)
    await publisher.send("property-extraction-queue", DomainEvent(event_type="X.v1", data={}))

    assert connection.channel.call_count == 2


async def test_send_raises_publish_failed_after_retry_with_queue_as_sink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On terminal exhaustion the command publisher's structured `sink`
    is the queue name (vs the exchange name for the event publisher)."""
    from shared.events.adapters._publish_retry import PublishFailedAfterRetry

    async def _noop(_seconds: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _noop)

    connection = MagicMock()
    failing_ctx = AsyncMock()
    failing_ctx.__aenter__ = AsyncMock(side_effect=RuntimeError("Connection was not opened"))
    failing_ctx.__aexit__ = AsyncMock(return_value=None)
    connection.channel = MagicMock(return_value=failing_ctx)

    publisher = RabbitMQCommandPublisher(connection)
    with pytest.raises(PublishFailedAfterRetry) as exc_info:
        await publisher.send("property-extraction-queue", DomainEvent(event_type="X.v1", data={}))

    assert exc_info.value.sink == "property-extraction-queue"
    assert exc_info.value.attempts == 3
