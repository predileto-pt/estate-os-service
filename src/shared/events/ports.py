"""Provider-neutral ports for the event bus.

ADR-008 decided that events / commands share a single `DomainEvent` envelope
and flow through four Protocol ports. Handler code depends on these ports
only; swapping SQS+SNS for RabbitMQ or Kafka is an adapter change.

- `EventPublisher` — broadcast via SNS fan-out. Publisher doesn't know who listens.
- `CommandPublisher` — point-to-point via SQS. Publisher knows which queue.
- `Message` — one delivery of a `DomainEvent`, owns ack/nack/heartbeat.
- `MessageConsumer` — opens a polling session over a named queue.
"""

from typing import Any, Protocol

from shared.events.base import DomainEvent


class EventPublisher(Protocol):
    """Broadcast via SNS fan-out. Subscribers opt in via SNS→SQS subscription."""

    async def publish(self, event: DomainEvent) -> None: ...


class CommandPublisher(Protocol):
    """Point-to-point via SQS. Single intended consumer per queue.

    Same envelope as `EventPublisher`; different transport semantics (no fan-out).
    """

    async def send(self, queue_url: str, event: DomainEvent) -> None: ...


class Message(Protocol):
    """One delivery of a `DomainEvent`. Owns its own ack/nack handle."""

    @property
    def event(self) -> DomainEvent: ...
    @property
    def message_id(self) -> str: ...
    async def ack(self) -> None: ...
    async def nack(self) -> None: ...
    async def extend_visibility(self, seconds: int) -> None: ...


class MessageConsumer(Protocol):
    """Opens a polling session on a named stream/queue/topic-subscription."""

    async def __aenter__(self) -> "MessageConsumer": ...
    async def __aexit__(self, *exc: Any) -> None: ...
    async def poll(self, max_messages: int, wait_seconds: int) -> list[Message]: ...
