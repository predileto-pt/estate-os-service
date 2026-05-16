# ADR-008: Event bus ports, SNS fan-out, and context-owned workers

**Date:** 2026-04-17
**Status:** Proposed

## Context

ADR-007 established a unified domain events bus: one `DomainEvent` envelope, one shared SQS queue, one `DomainEventsWorker` that fans out via an in-process `EventRouter`. That was the right move at the time. It is not the right place to stay.

### The state we're in

- **Four `DomainEvent` classes exist** across bounded contexts. The canonical one at `src/shared/events/base.py:9` is used by publishers in `properties` today, but duplicates still live at `src/properties/domain/events.py:7`, `src/customers/domain/events.py:7`, and `src/screening/domain/models/domain_event.py:15`. ADR-007 declared the unified shape; the cleanup never finished.
- **Four SQS-worker implementations exist.** `contract_intelligence`, `screening`, and `properties` each have their own ADR-006-compliant `SQSWorker` class (copy-paste with small context-specific deltas). `src/shared/entrypoints/events_worker.py` has its own pre-ADR-006 `DomainEventsWorker` — the last holdout. Four copies of the same ~200 lines, divergence already visible.
- **No true pub/sub.** Every domain event currently lands on the single `sqs_domain_events_queue`. Every handler registered on the shared router runs for every event of its type, on the same worker process. This means:
  - A poison message for handler A blocks handler B, because there's only one DLQ at the queue level (explicit negative in ADR-007 §"No per-handler DLQ").
  - A slow handler (LLM call, external HTTP) starves every other handler sharing the worker.
  - There is no way to scale one handler independently of another — they share the polling budget.
- **No abstraction over the transport.** `DomainEventPublisher` is a port; `SQSDomainEventPublisher` is its only adapter. But consumers are not symmetric — `DomainEventsWorker` is SQS-native end-to-end (receipt handles, `change_message_visibility`, `delete_message` leak through the worker code into every handler test). Swapping SQS for RabbitMQ / Kafka means rewriting workers, not just the transport adapter.

### The forcing function

The next two specs on deck (`carried-state-events-and-property-listings-projector.md` and `listings-cursor-pagination-and-filters.md`) make this pain concrete:

- The listings projector will call an external LLM inside a handler. On the current shared worker, an LLM stall >30s trips the default visibility timeout and causes mid-processing redelivery — there is no heartbeat. A persistent LLM failure on one event type loops the whole worker on `sleep(5)` forever, because there is no DLQ.
- The projector will emit a second internal event (`PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT`) that only the listings context cares about. Every other consumer has to filter it out. Every handler sees every event.
- Shipping the listings projector on today's infrastructure means shipping a known single-point-of-failure. Shipping it on tomorrow's infrastructure means doing the ADR-007 "Future improvements" now.

### The core tension

ADR-007 §"Future improvements" already named this:

> - **SNS fan-out**: Replace the single SQS queue with an SNS topic that fans out to per-handler SQS queues, giving true handler isolation and per-handler DLQs

We now add two more requirements the team has decided are non-negotiable:

1. **One implementation, not four.** The shared `SQSWorker` class is the only copy; every context instantiates it via a small factory.
2. **Pluggable transport.** SQS today, RabbitMQ or Kafka tomorrow. The port surface must not leak SQS receipt handles, SNS ARNs, or any vendor-specific concept into handler code or tests.

## Decision

### 1. One `DomainEvent` class

`src/shared/events/base.py` is the only `DomainEvent` in the repo. Its shape is frozen:

```python
@dataclass(frozen=True)
class DomainEvent:
    event_type: str                    # e.g. "PROPERTY_CREATED.v1"
    data: dict[str, Any]
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
```

The three duplicates (`properties/domain/events.py`, `customers/domain/events.py`, `screening/domain/models/domain_event.py`) are deleted. Their subclass-style events (`PropertyExtractionRequested`, `BatchPropertyExtractionRequested`, etc.) collapse into plain `DomainEvent(event_type="PROPERTY_EXTRACTION_REQUESTED.v1", data={...})` calls.

**Versioning is encoded in the event type string**: `PROPERTY_CREATED.v1`, `PROPERTY_UPDATED.v1`. Schema evolution is a new version string published alongside the old one for a transition period. No extra fields on the envelope.

### 2. Provider-neutral ports

Three ports in `src/shared/events/ports.py`:

```python
class EventPublisher(Protocol):
    """Publishes a DomainEvent. Transport decides the routing key."""
    async def publish(self, event: DomainEvent) -> None: ...


class Message(Protocol):
    """One delivery of a DomainEvent. Owns its own ack/nack handle."""
    @property
    def event(self) -> DomainEvent: ...
    @property
    def message_id(self) -> str: ...
    async def ack(self) -> None: ...      # SQS delete_message; RabbitMQ basic.ack; Kafka commit
    async def nack(self) -> None: ...     # SQS no-op (will redeliver); RabbitMQ basic.nack; Kafka uncommit
    async def extend_visibility(self, seconds: int) -> None: ...   # heartbeat / deadline extension


class MessageConsumer(Protocol):
    """Opens a polling session on a named stream/queue/topic-subscription."""
    async def __aenter__(self) -> "MessageConsumer": ...
    async def __aexit__(self, *exc: Any) -> None: ...
    async def poll(self, max_messages: int, wait_seconds: int) -> list[Message]: ...
```

Handlers take `(event_data: dict, context: Any)` as today. They never touch `Message` directly — the shared worker owns ack/nack/heartbeat.

### 3. SNS fan-out topology

For every event type, one SNS topic. For every context that subscribes, one SQS queue subscribed to the topics it cares about.

```
                                   ┌──────────────────────────┐
                                   │ properties-events-queue  │ ── properties worker
          ┌────── SNS ──────►──────┤  (sub: PROPERTY_CREATED) │
publish ─►│  PROPERTY_CREATED.v1   │
          │       SNS topic        │                          │
          └───────┬────────────────┘
                  │          ┌──────────────────────────┐
                  └──────────┤  listings-events-queue   │ ── listings worker
                             │  (sub: PROPERTY_CREATED, │
                             │        PROPERTY_UPDATED, │
                             │        PROPERTY_DELETED) │
                             └──────────────────────────┘
```

- **Isolation**: a poison `PROPERTY_CREATED.v1` message only blocks the listings worker — the properties worker's copy (delivered to its own queue) succeeds independently.
- **Per-context DLQ**: each SQS queue has its own redrive policy. Poison messages land in `listings-events-dlq`, not a shared graveyard.
- **Independent scaling**: each context worker is its own process group with its own concurrency and backpressure.
- **Subscription is explicit**: a context only receives events it explicitly subscribes to. No client-side filtering waste.

Publisher is topic-aware: `SQSSNSEventPublisher.publish(event)` resolves the SNS topic ARN from `event.event_type` via a naming convention (`arn:aws:sns:<region>:<account>:domain-events-${event_type}`) and calls `sns.publish(TopicArn=..., Message=event.to_json())`.

### 4. Single shared `SQSWorker` class

The ADR-006-compliant `SQSWorker` (today copied in `contract_intelligence`, `screening`, and `properties`) moves to `src/shared/events/worker.py`. It:

- Accepts a `MessageConsumer` (the port, not a raw `aioboto3` session).
- Accepts a `router: EventRouter` and a `context: dict`.
- Implements every ADR-006 decision: client reuse, batch polling, bounded concurrency, contextvars, per-message try/except, heartbeat, graceful drain, structured error logging.
- On handler exception: **does not ack**. The transport-level redrive policy decides when to DLQ.

Each context has a tiny CLI entrypoint that:

1. Builds a `MessageConsumer` adapter pointed at the context's queue URL.
2. Registers the context's handlers on a local `EventRouter`.
3. Instantiates `SQSWorker(consumer, router, context)` and awaits `run()`.

The pre-ADR-006 `DomainEventsWorker` at `src/shared/entrypoints/events_worker.py` is deleted. The `APPLICANT_SCREENED` handler dispatch that currently happens there migrates into per-context workers (customers + bookings).

### 5. Versioned event type registry

All event type constants live in `src/shared/events/types.py` and include the version:

```python
PROPERTY_CREATED_V1 = "PROPERTY_CREATED.v1"
PROPERTY_UPDATED_V1 = "PROPERTY_UPDATED.v1"
PROPERTY_DELETED_V1 = "PROPERTY_DELETED.v1"
PROPERTY_EXTRACTION_REQUESTED_V1 = "PROPERTY_EXTRACTION_REQUESTED.v1"
# ...
APPLICANT_SCREENED_V1 = "APPLICANT_SCREENED.v1"
```

Bumping a schema is "publish both V1 and V2 for a deprecation window; migrate consumers; drop V1". No envelope changes, no optional metadata fields.

### 6. Migration path

This is a brown-field cutover. Order matters.

1. **ADR-008 lands.**
2. **Foundation spec lands** (next spec, `event-bus-ports-and-fanout-foundation.md`):
   a. Add ports (`EventPublisher`, `Message`, `MessageConsumer`).
   b. Implement SQS/SNS adapters.
   c. Extract shared `SQSWorker` with full ADR-006 semantics.
   d. SNS topics + per-context queues provisioned (IaC change, out of this repo).
   e. Each context gets a worker CLI entrypoint.
   f. Delete the three duplicate `DomainEvent` classes + the three per-context `SQSWorker` copies (properties, screening, contract_intelligence — all three become thin factories around the shared class).
   g. Delete `src/shared/entrypoints/events_worker.py`.
   h. Rename every event type constant to its `.v1`-suffixed form; update every publish site and handler registration.
3. **Projector spec** (`carried-state-events-and-property-listings-projector.md`) ships on the new foundation — cleanly.
4. **Listings feature spec** (`listings-cursor-pagination-and-filters.md`) ships on top.

The foundation spec is the big hairy one. It is a breaking change to internal infrastructure, but no external HTTP contract changes. It ships in a single release to every service, or behind a feature flag if deployed gradually.

## Consequences

### Positive

- **Handler isolation.** A poison message in one context never affects another.
- **Per-context DLQ.** Failure investigation scoped to the team that owns the context.
- **One worker implementation** — no drift between contract_intelligence, screening, properties, and shared.
- **One `DomainEvent`** — no drift between contexts' subclass-based shapes and the shared dict-based shape.
- **Provider-neutral handler code.** Swapping SQS/SNS for RabbitMQ or Kafka is an adapter change, not a handler rewrite.
- **Explicit subscriptions.** Consumers opt into events; no client-side filtering waste.
- **Independent scaling.** Each context worker is its own Kubernetes deployment.
- **Schema versioning that survives broker swaps.** Versions live in the event-type string, which every broker models (SNS topic name, Kafka topic, RabbitMQ routing key).

### Negative

- **Infrastructure sprawl.** One SNS topic per event type, one SQS queue per context, one DLQ per queue. Counts grow with event types and contexts. Provisioning via IaC, not by hand.
- **Cross-context fan-out has a real dollar cost.** SNS charges per publish and per SQS subscription delivery. At the volumes we're projecting (<1 event/sec average) this is rounding-error; at 100× it matters.
- **Schema-registry pressure.** Once event types are versioned strings, we'll want a registry eventually. Deferred explicitly — until we have it, the `src/shared/events/types.py` module is the registry-by-convention.
- **No ordering across topics.** SNS does not guarantee order between topics. Already true on SQS today; SNS makes it explicit.
- **Outbox pattern still unsolved.** Commit-then-publish gap still exists. Separate follow-up.
- **Migration window is risky.** While contexts are moving off the shared queue onto their own queues, both paths must coexist. Brief period where a missed reconfiguration drops events. Mitigation: ship every context in the same release.

### Explicit non-decisions

- **Transactional outbox.** Out of scope. `try/except` + log on publish failure remains the pattern.
- **Event sourcing.** No replay log; events are notifications, not the source of truth.
- **Schema registry.** No runtime validation; `src/shared/events/types.py` is the contract file.
- **Extracting to a shared library.** The abstraction lives in this monorepo; moving it to a pypi package is a future conversation.

### Future improvements

- **Schema registry** (Confluent-style or JSON-Schema-based) for machine-validated events.
- **Transactional outbox** to close the commit-then-publish race window.
- **Kafka adapter** for event retention + replay, if we ever need either.
- **Per-event-type retention tuning** (some events we want to retain for weeks, others are ephemeral).

## Addendum — 2026-05-13: RabbitMQ as the active transport

Spec `2026-05-rabbitmq-transport-adapter` lands three new adapters in `src/shared/events/adapters/` — `RabbitMQEventPublisher`, `RabbitMQCommandPublisher`, `RabbitMQMessageConsumer` (+ `RabbitMQMessage`) — built on `aio-pika`. The four Protocol ports are unchanged; this validates the ADR's "pluggable transport" claim.

**The cutover is one-way.** `src/shared/entrypoints/bootstrap.py` now imports the RabbitMQ adapters directly — no runtime `EVENT_BUS_BACKEND` flag. The SNS+SQS adapter classes stay in the repo for unit tests + emergency revert; no production code path imports them.

**Topology mapping (SQS → RabbitMQ):**

| SNS/SQS concept | RabbitMQ equivalent |
|---|---|
| SNS topic per event_type | Topic exchange `domain-events`, routing-key = `event.event_type` |
| Per-context SQS queue subscribed to multiple SNS topics | Queue bound to `domain-events` with multiple routing-key patterns |
| SQS `maxReceiveCount=5` | Queue arg `x-delivery-limit=5` on a `quorum` queue |
| Per-queue DLQ via redrive policy | Single global DLX `domain-events-dlx` (fanout), one `dead-letters` queue bound to it. `x-death` headers identify origin |
| SNS `publish` durability | Channel-per-publish with `publisher_confirms=True` |
| SQS visibility timeout + heartbeat | Broker-side `consumer_timeout` (default 30 min); `extend_visibility` is a no-op on the consumer |
| Command-queue routing (point-to-point) | Default exchange (`""`), routing-key = queue name, `mandatory=True` (publisher raises on misroute) |

**Reliability primitives** (all set explicitly because RabbitMQ doesn't provide them implicitly):

- Publisher confirms on every channel.
- `delivery_mode=PERSISTENT` (=2) on every publish.
- `basic.qos(prefetch_count=max_concurrency)` on every consumer (=5, matches worker's `Semaphore(5)`).
- `mandatory=True` on the command publisher so a misroute is loud.
- AMQP heartbeat = 30s on `connect_robust`.
- One channel per publish (cheap; isolates channel-level errors).
- Internal `asyncio.Queue` buffer in the consumer adapter bridges RabbitMQ's push model to the `MessageConsumer.poll()` pull contract.

**Idempotency property is now load-bearing.** RabbitMQ is at-least-once like SQS, but reconnect storms re-deliver every unacked message *immediately* (vs. SQS's "wait for visibility timeout"). Handlers must be idempotent.

**Worker class renamed `SQSWorker` → `EventBusWorker`** in the same spec since it's transport-agnostic post-cutover (depends only on the `MessageConsumer` Protocol). All 6 context worker entrypoints updated to import the new name. Worker entrypoints also pass `use_heartbeat=False` on `EventBusWorker` — the `_heartbeat` task calls `extend_visibility` which is a no-op on RabbitMQ.

**Operational handoff:**

- Dev: `docker compose up -d` now runs `rabbitmq:3.13-management-alpine` (5672 + 15672, guest/guest). LocalStack is S3-only.
- Prod (Coolify): handled by spec `2026-05-coolify-compose-prod`.

## Addendum — 2026-05-16: publish-side reliability contract

After the SNS→RabbitMQ cutover, production surfaced a class of failures the original spec's "channel-per-publish + publisher_confirms" primitives didn't cover: **transient `RuntimeError("Connection was not opened")` during reconnect windows**. The trigger is a back-to-back redeploy (Coolify rolling the api container while RabbitMQ is mid-restart), but the same race exists for any heartbeat-driven reconnect, network blip, or broker brownout.

The original design treated publish failures as best-effort with caller-side `try/except Exception: log.exception(...)` — so the user-facing operation completed, but downstream consumers (listings projection, search index) silently missed the event.

**Resolution:** spec `rabbitmq-publish-reliability` (2026-05-16) added a bounded retry layer to both `RabbitMQEventPublisher.publish` and `RabbitMQCommandPublisher.send`, plus a startup readiness probe.

**Contract:**

- **Retry budget:** 3 attempts, 0.5s / 1.0s / 2.0s backoff. Total worst case ~3.5s blocking time per publish. Deliberately bounded — during a true broker outage we'd rather surface event-publish failure logs than amplify it into user-facing P99 latency.
- **Retriable errors** (the retry layer absorbs these): `RuntimeError("Connection was not opened")` (message-matched), `aio_pika.exceptions.AMQPConnectionError`, `aio_pika.exceptions.ChannelInvalidStateError`.
- **Non-retriable errors** (re-raised immediately, no retry, no `event_publish_attempt_failed` log): `aio_pika.exceptions.DeliveryError` (mandatory-publish unroutable — permanent routing-key misconfiguration), `aio_pika.exceptions.AMQPChannelError` on declare (broker rejected declaration — permanent), `aio_pika.exceptions.ProbableAuthenticationError`, any non-AMQP exception (caller bug, not transport problem).
- **Terminal log line** (fires from inside the adapter, not from `emit_*` wrappers, so direct-publish callers get the rich signal too): `event_publish_failed` at error level with `event_id`, `event_type`, `sink` (exchange or queue name), `attempts`, `error_class`, `error` structured fields.
- **Terminal exception**: `PublishFailedAfterRetry` subclassing `aio_pika.exceptions.AMQPError` (so `except AMQPError` and `except Exception` both catch). Last underlying exception chained via `__cause__`.
- **Startup probe**: lifespan opens one channel with a 5s timeout after `connect_robust`. Non-fatal — a failed probe logs `amqp_readiness_probe_failed` (warning) and the api continues to boot in degraded "publish-retry" mode. Read endpoints unaffected.

**Why this isn't an outbox.** A transactional outbox (events written in the same DB transaction as the aggregate, drained by a publisher worker) is the next reliability tier and would give us true at-least-once delivery across api crashes — not just reconnect windows. We deliberately deferred it: the retry layer covers ~99% of observed failure modes for ~150 lines of code; the outbox is justified once retry-isn't-enough evidence emerges (e.g., RabbitMQ outage durations consistently exceeding the budget, persistent gaps in the listings projection).

**When to escalate to an outbox.** If `event_publish_failed` count over 1h ever exceeds (say) 0.1% of write-path use-case invocations, or if reconciliation jobs against the listings projection show persistent drift that maps back to publish failures, open a new spec. Until then, retry + structured logs are the active contract.

**Consumer side stays as-is** (out of scope for this addendum). The `EventBusWorker` poll loop already wraps `consumer.poll()` in `try/except Exception` with exponential backoff (`src/shared/events/worker.py:121-126`), and aio_pika's `RobustChannel` auto-recovers the underlying channel through a reconnect. If consumer-side bugs surface, open a separate `rabbitmq-consumer-reliability` spec.
