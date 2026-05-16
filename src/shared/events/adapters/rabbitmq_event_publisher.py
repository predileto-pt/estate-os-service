"""RabbitMQ-backed `EventPublisher`.

Publishes to a topic exchange with routing-key = `event.event_type`
(e.g. `PROPERTY_CREATED.v1`). Topic-exchange analogue of ADR-008's
"one SNS topic per event_type" pattern — subscribers bind queues with
routing-key patterns instead of subscribing one queue per topic.

Reliability primitives (spec `2026-05-rabbitmq-transport-adapter` §3):
- Channel-per-publish with `publisher_confirms=True`: `publish()` returns
  only after the broker `basic.ack`s the delivery. Matches SNS's
  "durable once `publish` returns" guarantee.
- `delivery_mode=PERSISTENT` (=2): message survives broker restart in a
  durable queue.
- AMQP `message_id` property = `event.event_id` so the consumer can read
  it back via `Message.message_id`.
"""

import structlog
from aio_pika import DeliveryMode, ExchangeType, Message
from aio_pika.abc import AbstractRobustConnection

from shared.events.adapters._publish_retry import publish_with_retry
from shared.events.base import DomainEvent

log = structlog.get_logger()


class RabbitMQEventPublisher:
    def __init__(
        self,
        connection: AbstractRobustConnection,
        exchange: str = "domain-events",
    ) -> None:
        self._connection = connection
        self._exchange_name = exchange

    async def publish(self, event: DomainEvent) -> None:
        async def body() -> None:
            # Channel-per-publish isolates channel-level errors. AMQP channels
            # are cheap — orders of magnitude lighter than a TCP connection.
            async with self._connection.channel(publisher_confirms=True) as channel:
                exchange = await channel.declare_exchange(
                    self._exchange_name,
                    ExchangeType.TOPIC,
                    durable=True,
                )
                message = Message(
                    body=event.to_json().encode("utf-8"),
                    message_id=event.event_id,
                    delivery_mode=DeliveryMode.PERSISTENT,
                    content_type="application/json",
                )
                await exchange.publish(message, routing_key=event.event_type)

        await publish_with_retry(
            body,
            event_id=event.event_id,
            event_type=event.event_type,
            sink=self._exchange_name,
        )
        log.info(
            "domain_event_published",
            event_type=event.event_type,
            event_id=event.event_id,
            exchange=self._exchange_name,
        )
