"""RabbitMQ-backed `CommandPublisher`.

Commands are point-to-point — one queue per command type. Publishes to
the default exchange (`""`) with routing-key = `queue_url` (interpreted
as queue name in RabbitMQ-land). Symmetric to `SQSCommandPublisher`; the
param name `queue_url` is kept for port-compatibility.

Reliability primitives (spec `2026-05-rabbitmq-transport-adapter` §3):
- Channel-per-publish with `publisher_confirms=True`: `send()` returns
  only after the broker `basic.ack`s the delivery.
- `delivery_mode=PERSISTENT` (=2).
- `mandatory=True`: if no queue is bound to the routing key (typo in
  `queue_url`, queue not declared yet), the broker returns the message
  via `basic.return` and aio-pika raises `DeliveryError`. Catches the
  most common silent-failure mode of AMQP.
- AMQP `message_id` = `event.event_id`.
"""

import structlog
from aio_pika import DeliveryMode, Message
from aio_pika.abc import AbstractRobustConnection

from shared.events.base import DomainEvent

log = structlog.get_logger()


class RabbitMQCommandPublisher:
    def __init__(self, connection: AbstractRobustConnection) -> None:
        self._connection = connection

    async def send(self, queue_url: str, event: DomainEvent) -> None:
        async with self._connection.channel(publisher_confirms=True) as channel:
            message = Message(
                body=event.to_json().encode("utf-8"),
                message_id=event.event_id,
                delivery_mode=DeliveryMode.PERSISTENT,
                content_type="application/json",
            )
            # Default exchange routes by queue name. `mandatory=True`
            # raises `DeliveryError` if no queue with that name exists,
            # rather than silently dropping the message.
            await channel.default_exchange.publish(
                message,
                routing_key=queue_url,
                mandatory=True,
            )
        log.info(
            "command_sent",
            event_type=event.event_type,
            event_id=event.event_id,
            queue=queue_url,
        )
