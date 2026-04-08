# ADR-006: Unified domain events bus with dedicated command queues

**Date:** 2026-03-28
**Status:** Accepted

## Context

The estate-os-service has five bounded contexts that communicate asynchronously via SQS. Before this change, the event infrastructure had grown organically and accumulated several problems:

| Problem | Detail |
|---------|--------|
| 6 SQS queues | extraction, screening, domain-events, discovery, contract-ingestion, contract-analysis — each wired independently |
| 3 serialization formats | Some queues sent `{"event_type": ..., "data": {...}}`, others sent flat payloads like `{"applicant_id": "..."}`, and the screening pipeline sent Pydantic `.model_dump()` output with no envelope |
| No unified event structure | Each producer invented its own message shape. Consumers had to know the exact format of their specific queue |
| Cross-context routing was ad-hoc | `APPLICANT_SCREENED` needed to reach both `customer_management` (email notification) and `booking_management` (create booking applicant). This was handled by duplicating the SQS subscription or having a single Lambda forward to multiple handlers |
| Commands mixed with events | Internal pipeline steps ("extract this document", "screen this applicant") were published to the same infrastructure as domain events ("an applicant was screened"), making it impossible to scale or configure them independently |

### The core tension

Domain events and pipeline commands have fundamentally different characteristics:

- **Domain events** are broadcast — multiple consumers, past tense, the producer does not know or care who listens. Example: `APPLICANT_SCREENED`.
- **Pipeline commands** are targeted — one consumer, imperative, the consumer does specific work. Example: `{"applicant_id": "..."}` on the screening queue.

Mixing them on the same infrastructure prevents independent scaling (extraction is CPU-heavy, event routing is fast) and conflates retry semantics (a failed event handler should not block command processing).

## Decision

### 1. Unified domain events bus

A single SQS queue (`sqs_domain_events_queue_url`) carries all cross-context domain events. Every event uses a standard envelope:

```python
@dataclass(frozen=True)
class DomainEvent:
    event_type: str                    # "APPLICANT_SCREENED", "PROPERTY_CREATED"
    data: dict[str, Any]               # event-specific payload
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "event_id": self.event_id,
            "occurred_at": self.occurred_at,
            "data": self.data,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DomainEvent":
        return cls(
            event_type=d["event_type"],
            data=d.get("data", {}),
            event_id=d.get("event_id", str(uuid4())),
            occurred_at=d.get("occurred_at", datetime.now(timezone.utc).isoformat()),
        )
```

### 2. Publisher port (ABC)

Services depend on an abstract publisher, not on SQS:

```python
class DomainEventPublisher(ABC):
    @abstractmethod
    async def publish(self, event: DomainEvent) -> None: ...
```

Lives in `shared/events/publisher.py`. The SQS implementation lives in `shared/adapters/sqs_event_publisher.py`:

```python
class SQSDomainEventPublisher(DomainEventPublisher):
    def __init__(
        self,
        session: aioboto3.Session,
        queue_url: str,
        endpoint_url: str | None = None,
    ) -> None:
        self._session = session
        self._queue_url = queue_url
        self._endpoint_url = endpoint_url

    async def publish(self, event: DomainEvent) -> None:
        async with self._session.client("sqs", **self._client_kwargs()) as sqs:
            await sqs.send_message(
                QueueUrl=self._queue_url,
                MessageBody=event.to_json(),
            )
        logger.info(
            "domain_event_published",
            event_type=event.event_type,
            event_id=event.event_id,
        )
```

### 3. EventRouter for multi-handler dispatch

```python
class EventRouter:
    def __init__(self) -> None:
        self._handlers: dict[str, list[HandlerFn]] = defaultdict(list)

    def on(self, event_type: str, handler: HandlerFn) -> None:
        self._handlers[event_type].append(handler)

    async def dispatch(self, event: DomainEvent, context: Any) -> None:
        handlers = self._handlers.get(event.event_type, [])
        if not handlers:
            logger.warning("no_handler_for_event", event_type=event.event_type)
            return

        for handler in handlers:
            try:
                await handler(event.data, context)
            except Exception:
                logger.exception(
                    "event_handler_failed",
                    event_type=event.event_type,
                    event_id=event.event_id,
                )
                raise
```

### 4. Handler registration in the events worker

`_build_router()` in `shared/entrypoints/events_worker.py` wires handlers from multiple bounded contexts to event types:

```python
def _build_router() -> EventRouter:
    from bookings.adapters.events.handlers import handle_applicant_screened
    from customers.adapters.workers.event_processor import (
        _handle_applicant_screened as cm_handle_applicant_screened,
    )
    from properties.adapters.workers.discovery_processor import (
        handle_property_created,
    )

    router = EventRouter()
    router.on(APPLICANT_SCREENED, cm_handle_applicant_screened)  # email notification
    router.on(APPLICANT_SCREENED, handle_applicant_screened)      # create booking applicant
    router.on(PROPERTY_CREATED, handle_property_created)          # discover amenities
    return router
```

### 5. DomainEventsWorker

A single long-running worker polls the domain events queue, deserializes messages into `DomainEvent`, dispatches through the router, and deletes on success:

```python
class DomainEventsWorker:
    def __init__(self, session, queue_url, router, context, endpoint_url=None):
        # ... store dependencies, set self._running = True

    async def run(self) -> None:
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._shutdown)

        while self._running:
            try:
                async with self._session.client("sqs", ...) as sqs:
                    response = await sqs.receive_message(
                        QueueUrl=self._queue_url,
                        MaxNumberOfMessages=1,
                        WaitTimeSeconds=20,
                    )
                    for msg in response.get("Messages", []):
                        event = DomainEvent.from_dict(json.loads(msg["Body"]))
                        await self._router.dispatch(event, self._context)
                        await sqs.delete_message(
                            QueueUrl=self._queue_url,
                            ReceiptHandle=msg["ReceiptHandle"],
                        )
            except Exception:
                log.exception("domain_events_worker_error")
                await asyncio.sleep(5)
```

### 6. Command queues stay separate

Internal pipeline commands remain on dedicated SQS queues:

- **Extraction queue**: `{document_id, applicant_id}` — consumed by the extraction worker
- **Screening queue**: `{applicant_id}` — consumed by the screening worker
- **Contract ingestion queue**: `{document_id}` — consumed by the ingestion worker
- **Contract analysis queue**: `{document_id}` — consumed by the analysis worker

These use the `MessagePublisher` port (`publish(queue_url, message_dict)`) where the queue URL is passed per call, allowing a single publisher instance to target different queues. This is distinct from `DomainEventPublisher` which is bound to a single queue at construction.

### 7. Publishing after commit

Domain events and command messages are always published AFTER the database transaction commits. Services use a `should_publish` flag pattern:

```python
should_publish = False
async with self._uow:
    # ... do work ...
    await self._uow.commit()
    should_publish = True

if should_publish:
    await self._domain_event_publisher.publish(DomainEvent(...))
```

This prevents a race condition where a consumer reads the event and queries the database before the producing transaction has committed.

## Consequences

### Positive

- **Single queue for cross-context events** — simpler infrastructure, one worker to deploy and monitor
- **Multiple handlers per event** — `APPLICANT_SCREENED` naturally fans out to customer_management and booking_management without message duplication
- **Unified envelope** — every event has `event_type`, `event_id`, `occurred_at`, `data`. No more guessing the payload shape
- **Independent command scaling** — extraction workers can scale separately from the events worker, with different visibility timeouts and retry policies
- **Clean conceptual split** — domain events (things that happened) vs commands (work to be done) are easy to reason about

### Negative

- **At-least-once delivery** — SQS standard queues deliver at least once. Handlers must be idempotent (screening service already has dedup checks)
- **No message ordering** — SQS standard queues do not guarantee order. Events may arrive out of sequence
- **No distributed transactions** — database commit and SQS publish are two separate operations. If the publish fails after commit, the event is lost (mitigated by the try/except + logging pattern in `CreateProperty`)
- **Handler coupling in dispatch** — if one handler for `APPLICANT_SCREENED` fails, the exception propagates and the message returns to the queue. ALL handlers re-run, not just the failed one
- **No per-handler DLQ** — dead-letter queue is per SQS queue, not per handler. A poison message blocks all handlers for that event type

### Future improvements

- **SNS fan-out**: Replace the single SQS queue with an SNS topic that fans out to per-handler SQS queues, giving true handler isolation and per-handler DLQs
- **Event schema registry**: Typed event classes per event type instead of `dict[str, Any]` for the `data` field
- **Outbox pattern**: Write events to a database outbox table in the same transaction, then relay to SQS asynchronously to eliminate the commit-then-publish gap
