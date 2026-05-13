"""RabbitMQ-backed `MessageConsumer` + `Message`.

Bridges the pull-based `MessageConsumer.poll()` protocol with RabbitMQ's
push model via an internal `asyncio.Queue` buffer fed by a background
pump driving `queue.iterator()`. The buffer is bounded at
`prefetch_count` so QoS is what actually back-pressures the worker.

Reliability primitives (spec `2026-05-rabbitmq-transport-adapter` §3):
- `basic.qos(prefetch_count=N)`: broker delivers at most N unacked
  messages at a time. Matches SQS's per-poll `MaxNumberOfMessages` and
  prevents mass-redelivery on reconnect.
- Queue declared with `x-queue-type=quorum` + `x-delivery-limit=5` +
  `x-dead-letter-exchange=<dlx>`: after the 5th `basic.nack(requeue=true)`
  the broker auto-routes to the DLX. Matches SQS `maxReceiveCount=5`.
- `Message.nack` = `basic.nack(requeue=True)` so the broker counts the
  redelivery against `x-delivery-limit`.
- `Message.extend_visibility` is a **no-op**: RabbitMQ has no per-message
  visibility timeout. Broker-side `consumer_timeout` (default 30 min) is
  the hard ceiling.
- `Message.message_id` returns the AMQP `message_id` property the
  publisher set (= `event.event_id`); falls back to delivery tag only if
  absent (shouldn't happen with our publishers).
"""

import asyncio
import json
from typing import Any

import structlog
from aio_pika import ExchangeType
from aio_pika.abc import AbstractIncomingMessage, AbstractRobustConnection

from shared.events.base import DomainEvent

log = structlog.get_logger()


class RabbitMQMessage:
    def __init__(self, raw: AbstractIncomingMessage) -> None:
        self._raw = raw
        # Handle both SNS-wrapped envelopes (legacy SNS+SQS handlers may
        # emit this shape via the old code path) and raw DomainEvent JSON.
        body = json.loads(raw.body.decode("utf-8"))
        event_json = (
            json.loads(body["Message"])
            if isinstance(body, dict) and "Message" in body
            else body
        )
        self._event = DomainEvent.from_dict(event_json)

    @property
    def event(self) -> DomainEvent:
        return self._event

    @property
    def message_id(self) -> str:
        # Publishers set the AMQP `message_id` property to `event.event_id`.
        # Falls back to delivery tag if absent — only a concern for messages
        # published by an external producer outside our adapters.
        return self._raw.message_id or str(self._raw.delivery_tag)

    async def ack(self) -> None:
        await self._raw.ack()

    async def nack(self) -> None:
        # `requeue=True` lets the broker count the redelivery against the
        # queue's `x-delivery-limit`. After the limit, broker auto-routes
        # to the DLX. Matches SQS `maxReceiveCount` semantics.
        await self._raw.nack(requeue=True)

    async def extend_visibility(self, seconds: int) -> None:
        # No-op on RabbitMQ — there is no per-message visibility timeout.
        # Broker tracks unacked messages at the channel level; the broker's
        # `consumer_timeout` (default 30 min) is the hard ceiling. If a
        # handler ever needs to run longer, bump `consumer_timeout` via
        # `rabbitmq.conf` or `rabbitmqctl set_parameter`.
        return None


class RabbitMQMessageConsumer:
    """Pull-based consumer adapter over aio-pika's push-based iterator."""

    def __init__(
        self,
        connection: AbstractRobustConnection,
        queue_name: str,
        bindings: list[tuple[str, str]] | None = None,
        prefetch_count: int = 5,
        dlx: str = "domain-events-dlx",
    ) -> None:
        # bindings: list of (exchange_name, routing_key_pattern) tuples.
        # Empty for command queues (no exchange binding; consumes from
        # the default-exchange-routed queue directly).
        self._connection = connection
        self._queue_name = queue_name
        self._bindings = bindings or []
        self._prefetch = prefetch_count
        self._dlx = dlx
        self._channel: Any = None
        self._queue: Any = None
        self._buffer: asyncio.Queue[RabbitMQMessage] | None = None
        self._pump_task: asyncio.Task | None = None

    async def __aenter__(self) -> "RabbitMQMessageConsumer":
        self._channel = await self._connection.channel()
        await self._channel.set_qos(prefetch_count=self._prefetch)
        # Declare the DLX (fanout) + the global `dead-letters` queue bound
        # to it. Both idempotent — RabbitMQ `declare` is a no-op on existing
        # resources. Without this, dead-lettered messages would route to the
        # DLX with no bound queue and be silently discarded by the broker.
        dlx_exchange = await self._channel.declare_exchange(
            self._dlx, ExchangeType.FANOUT, durable=True
        )
        dead_letters_queue = await self._channel.declare_queue(
            "dead-letters", durable=True
        )
        await dead_letters_queue.bind(dlx_exchange)
        # Queue with the SQS-equivalent retry profile.
        self._queue = await self._channel.declare_queue(
            self._queue_name,
            durable=True,
            arguments={
                "x-queue-type": "quorum",
                "x-delivery-limit": 5,
                "x-dead-letter-exchange": self._dlx,
            },
        )
        # Bind to topic-exchange routing-key patterns (events queues).
        # Command queues pass bindings=[] and skip this loop.
        for exchange_name, routing_key in self._bindings:
            exchange = await self._channel.declare_exchange(
                exchange_name, ExchangeType.TOPIC, durable=True
            )
            await self._queue.bind(exchange, routing_key=routing_key)
        # Bounded buffer + background pump bridges push → pull.
        self._buffer = asyncio.Queue(maxsize=self._prefetch)
        self._pump_task = asyncio.create_task(self._pump())
        return self

    async def _pump(self) -> None:
        assert self._queue is not None
        assert self._buffer is not None
        async with self._queue.iterator() as it:
            async for raw in it:
                await self._buffer.put(RabbitMQMessage(raw))

    async def poll(
        self, max_messages: int, wait_seconds: int
    ) -> list[RabbitMQMessage]:
        assert self._buffer is not None
        out: list[RabbitMQMessage] = []
        deadline = asyncio.get_event_loop().time() + wait_seconds
        while len(out) < max_messages:
            remaining = max(0.0, deadline - asyncio.get_event_loop().time())
            try:
                msg = await asyncio.wait_for(
                    self._buffer.get(), timeout=remaining
                )
                out.append(msg)
            except asyncio.TimeoutError:
                break
        return out

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._pump_task is not None:
            self._pump_task.cancel()
            await asyncio.gather(self._pump_task, return_exceptions=True)
            self._pump_task = None
        if self._channel is not None:
            await self._channel.close()
            self._channel = None
