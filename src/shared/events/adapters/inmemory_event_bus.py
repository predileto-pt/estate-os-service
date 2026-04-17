"""In-memory test doubles for the event bus ports.

Replaces the ad-hoc `PropertyInMemoryEventBus` and `InMemoryEventBus`
variants scattered across bounded contexts. Used in unit tests and in
integration tests that don't need real SQS/SNS.

- `InMemoryEventPublisher` — stores every published `DomainEvent` in a
  list so tests can assert on the envelope shape.
- `InMemoryCommandPublisher` — stores `(queue_url, event)` tuples.
- `InMemoryMessageConsumer` + `InMemoryMessage` — emulate SQS polling
  semantics: `poll()` returns pending messages; `ack()` removes them;
  `nack()` makes them visible again on the next `poll()`.
"""

from typing import Any

from shared.events.base import DomainEvent


class InMemoryEventPublisher:
    def __init__(self) -> None:
        self.published: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.published.append(event)


class InMemoryCommandPublisher:
    def __init__(self) -> None:
        self.sent: list[tuple[str, DomainEvent]] = []

    async def send(self, queue_url: str, event: DomainEvent) -> None:
        self.sent.append((queue_url, event))


class InMemoryMessage:
    def __init__(
        self, event: DomainEvent, message_id: str, consumer: "InMemoryMessageConsumer"
    ) -> None:
        self._event = event
        self._message_id = message_id
        self._consumer = consumer

    @property
    def event(self) -> DomainEvent:
        return self._event

    @property
    def message_id(self) -> str:
        return self._message_id

    async def ack(self) -> None:
        self._consumer._acked.append(self._message_id)

    async def nack(self) -> None:
        # Re-queue the message so a subsequent `poll()` will return it again.
        self._consumer._pending.append(self)

    async def extend_visibility(self, seconds: int) -> None:
        # In-memory bus has no visibility-timeout concept; no-op.
        return None


class InMemoryMessageConsumer:
    """In-memory consumer that implements the `MessageConsumer` Protocol.

    Seed messages into it via `enqueue(event)` from test fixtures. The worker
    polls via `__aenter__` + `poll()` exactly as it would against SQS.
    """

    def __init__(self) -> None:
        self._pending: list[InMemoryMessage] = []
        self._acked: list[str] = []
        self._next_id = 0

    def enqueue(self, event: DomainEvent) -> None:
        self._next_id += 1
        self._pending.append(InMemoryMessage(event, f"msg-{self._next_id}", self))

    @property
    def acked(self) -> list[str]:
        return list(self._acked)

    @property
    def pending(self) -> list[InMemoryMessage]:
        return list(self._pending)

    async def __aenter__(self) -> "InMemoryMessageConsumer":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    async def poll(self, max_messages: int, wait_seconds: int) -> list[InMemoryMessage]:
        batch = self._pending[:max_messages]
        self._pending = self._pending[max_messages:]
        return batch
