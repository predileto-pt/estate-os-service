# Event bus ports, SNS fan-out, and context-owned workers — foundation

**Status:** in-progress
**Owner:** Peter
**Created:** 2026-04-17

## Problem

Three specific pain points, all flagged in ADR-007 §"Future improvements" and §"Negative", are now blocking upstream work:

1. **No handler isolation.** All cross-context domain events share a single SQS queue (`sqs_domain_events_queue_url`) and a single in-process `EventRouter` inside `src/shared/entrypoints/events_worker.py`. A poison message for one handler blocks every other handler for that event type. This is a documented negative consequence in ADR-007; the upcoming listings projector will make it critical (LLM address parser can fail, and the current worker has no per-handler DLQ to contain it).
2. **Five copies of the event-processing worker class, plus three `SQSMessageConsumer` duplicates.** `src/screening/entrypoints/worker.py:50`, `src/contract_intelligence/entrypoints/worker.py:53`, and `src/properties/entrypoints/worker.py:51` each have their own ADR-006-compliant `SQSWorker`. `src/shared/entrypoints/events_worker.py:57` has its own pre-ADR-006 `DomainEventsWorker`. `src/customers/adapters/workers/events_worker.py:12` has a fifth variant (`EventsWorker`). On top of that, `src/customers/adapters/queue/sqs_consumer.py:7`, `src/contract_intelligence/adapters/queue/sqs_publisher.py:23`, and `src/screening/adapters/queue/sqs_publisher.py:23` each reinvent their own `SQSMessageConsumer`. Eight classes of drifting infrastructure.
3. **Four copies of `DomainEvent`.** `src/shared/events/base.py:9` is the canonical one, but `src/properties/domain/events.py:7`, `src/customers/domain/events.py:7`, and `src/screening/domain/models/domain_event.py:15` are three duplicate classes (two of them with subclass-per-event patterns) that should have been removed when ADR-007 landed.

ADR-008 decided the architecture. This spec implements it.

## Goal

Ship the infrastructure described by ADR-008:

- One `DomainEvent` class in `src/shared/events/base.py`. The other three are deleted.
- Four provider-neutral ports in `src/shared/events/ports.py`: `EventPublisher` (broadcast), `CommandPublisher` (point-to-point), `Message`, `MessageConsumer`. Handlers never touch transport concerns.
- One `SQSWorker` class in `src/shared/events/worker.py` with full ADR-006 semantics (client reuse, batch + concurrency, contextvars, heartbeat, drain, no-ack-on-error). Every context — both domain-event workers and command-queue workers — reuses it. No bifurcated interface.
- **Domain events** use SNS fan-out: one SNS topic per event type; each context owns its own SQS queue subscribed to the topics it handles; each queue has its own DLQ with `maxReceiveCount=5`.
- **Commands** use direct SQS: one dedicated SQS queue per command type, published point-to-point via `CommandPublisher.send(queue_url, event)`, each queue has its own DLQ with `maxReceiveCount=5`. No SNS hop.
- Every event type string ends in `.v1` (or higher).
- Per-context worker CLI entrypoints. The legacy `src/shared/entrypoints/events_worker.py` is deleted.

No external HTTP contract changes. No behaviour change visible to API clients. Internal infrastructure cutover only.

## Non-goals

- Transactional outbox.
- Schema registry / runtime validation of `data` payloads.
- Kafka or RabbitMQ adapters — the ports are designed for them, the adapters are a future spec.
- Changes to any business logic in handlers. **Handler signatures are `(event: DomainEvent, context: Any) -> None`** — the shared worker hands the full envelope to the handler. `event_type` / `event_id` / `occurred_at` are first-class arguments on every handler, not smuggled through `structlog.contextvars`. (The three existing handlers — `cm_handle_applicant_screened`, `handle_applicant_screened`, `handle_property_created` — are migrated: `(data, ctx)` → `(event, ctx); data = event.data`. Mechanical rename.)
- Replay / event sourcing.
- Introducing new event types. That's Spec 2 (`carried-state-events-and-property-listings-projector.md`).
- Changing external CLI or queue URLs of the per-context command-queue workers. The command-queue workers for `extraction` (properties), `ingestion` / `analysis` / `dlq` (contract_intelligence), and `screening` / `extraction` (screening) keep their external CLI commands and queue URLs **unchanged**. Internally, their per-context `SQSWorker` classes are deleted and the CLIs are rewired to instantiate `shared.events.worker.SQSWorker`; their processor modules are rewired per §Command-queue processor split. Consumer behaviour on the happy path is identical from the outside — see §Behaviour change for the failure-path delta.

## Depends on

- ADR-008 accepted.
- Infrastructure provisioning (out of this repo): SNS topics per event type, per-context SQS queues subscribed to their topics, per-queue DLQs with `maxReceiveCount=5`. Document the naming convention here (`arn:aws:sns:<region>:<account>:domain-events-${event_type}`) and coordinate with whoever owns Terraform / infra-as-code.

## Approach

### Port definitions (`src/shared/events/ports.py`, new)

```python
from typing import Any, Protocol

from shared.events.base import DomainEvent


class EventPublisher(Protocol):
    """Broadcast via SNS fan-out. Subscribers opt in via SNS→SQS subscription.

    Used for domain events (PROPERTY_CREATED.v1, APPLICANT_SCREENED.v1, etc.) —
    publisher doesn't know or care who listens.
    """
    async def publish(self, event: DomainEvent) -> None: ...


class CommandPublisher(Protocol):
    """Point-to-point via SQS. Single intended consumer per queue.

    Used for command messages (APPLICANT_SCREENING_REQUESTED.v1,
    DOCUMENT_INGESTION_REQUESTED.v1, etc.) — publisher knows exactly which
    queue is the intended consumer. Same envelope as EventPublisher; different
    transport semantics (no fan-out).
    """
    async def send(self, queue_url: str, event: DomainEvent) -> None: ...


class Message(Protocol):
    @property
    def event(self) -> DomainEvent: ...
    @property
    def message_id(self) -> str: ...
    async def ack(self) -> None: ...
    async def nack(self) -> None: ...
    async def extend_visibility(self, seconds: int) -> None: ...


class MessageConsumer(Protocol):
    async def __aenter__(self) -> "MessageConsumer": ...
    async def __aexit__(self, *exc: Any) -> None: ...
    async def poll(self, max_messages: int, wait_seconds: int) -> list[Message]: ...
```

Pure `Protocol`s — no ABCs, no `abstractmethod`. Structural typing matches what the rest of the codebase does (`UserRepository`, `MembershipRepository`, etc. are `ABC` but the port pattern in `src/screening/application/ports/` is `Protocol`; either works, we pick `Protocol` for ports that don't carry shared state).

**Why two publisher ports?** Commands and domain events differ semantically at the publish level — commands are point-to-point, events are broadcast. The ports reflect that difference. Every other layer is unified: same `DomainEvent` envelope, same `(event, context)` handler signature, same `SQSWorker`, same DLQ mechanism. A developer writing a handler never knows whether its message arrived via SNS fan-out or direct SQS send — same envelope, same code path.

### SQS/SNS adapters

**Publisher (`src/shared/events/adapters/sns_event_publisher.py`, new):**

```python
class SNSEventPublisher(EventPublisher):
    def __init__(self, session: aioboto3.Session, topic_arn_prefix: str, endpoint_url: str | None = None):
        self._session = session
        self._topic_arn_prefix = topic_arn_prefix  # e.g. "arn:aws:sns:eu-west-1:123:domain-events-"
        self._endpoint_url = endpoint_url

    @staticmethod
    def _topic_suffix(event_type: str) -> str:
        # AWS SNS topic names allow only [A-Za-z0-9_-]. The event_type string uses a dot
        # for version separation (e.g. "PROPERTY_CREATED.v1") so it maps cleanly to Kafka /
        # RabbitMQ routing keys in the future. Translate the dot to a dash for the SNS name.
        return event_type.replace(".", "-")

    async def publish(self, event: DomainEvent) -> None:
        topic_arn = f"{self._topic_arn_prefix}{self._topic_suffix(event.event_type)}"
        kwargs = {"endpoint_url": self._endpoint_url} if self._endpoint_url else {}
        async with self._session.client("sns", **kwargs) as sns:
            await sns.publish(TopicArn=topic_arn, Message=event.to_json())
```

**SNS topic-name rule.** AWS SNS topic names permit only `[A-Za-z0-9_-]` — dots are rejected. The `event_type` string keeps its dot-form for Kafka/RabbitMQ portability; the publisher translates dots to dashes at publish time. Mapping:

| `event.event_type` | SNS topic suffix | Full topic name |
|---|---|---|
| `PROPERTY_CREATED.v1` | `PROPERTY_CREATED-v1` | `domain-events-PROPERTY_CREATED-v1` |
| `APPLICANT_SCREENED.v1` | `APPLICANT_SCREENED-v1` | `domain-events-APPLICANT_SCREENED-v1` |

No registry lookup needed. The prefix is a Settings field.

**Command publisher (`src/shared/events/adapters/sqs_command_publisher.py`, new):**

```python
class SQSCommandPublisher(CommandPublisher):
    def __init__(self, session: aioboto3.Session, endpoint_url: str | None = None):
        self._session = session
        self._endpoint_url = endpoint_url

    async def send(self, queue_url: str, event: DomainEvent) -> None:
        kwargs = {"endpoint_url": self._endpoint_url} if self._endpoint_url else {}
        async with self._session.client("sqs", **kwargs) as sqs:
            await sqs.send_message(QueueUrl=queue_url, MessageBody=event.to_json())
```

Replaces the existing `src/screening/adapters/queue/sqs_publisher.py:SQSMessagePublisher` and `src/contract_intelligence/adapters/queue/sqs_publisher.py:SQSMessagePublisher` — both are deleted. The only change for existing call sites is that the message payload is now `event.to_json()` (canonical envelope) instead of `json.dumps(raw_dict)` (flat).

**Consumer + Message (`src/shared/events/adapters/sqs_message_consumer.py`, new):**

```python
class SQSMessage:
    def __init__(self, sqs_client, queue_url: str, raw: dict):
        self._sqs = sqs_client
        self._queue_url = queue_url
        self._raw = raw
        # SNS→SQS delivers messages whose Body is a JSON envelope containing "Message" (the actual event JSON)
        body = json.loads(raw["Body"])
        event_json = json.loads(body["Message"]) if "Message" in body else body
        self._event = DomainEvent.from_dict(event_json)

    @property
    def event(self) -> DomainEvent: return self._event
    @property
    def message_id(self) -> str: return self._raw["MessageId"]

    async def ack(self) -> None:
        await self._sqs.delete_message(QueueUrl=self._queue_url, ReceiptHandle=self._raw["ReceiptHandle"])

    async def nack(self) -> None:
        # No-op on SQS: failing to ack lets the visibility timeout expire, SQS redelivers.
        # (We rely on the redrive policy's maxReceiveCount to DLQ after N failures.)
        pass

    async def extend_visibility(self, seconds: int) -> None:
        await self._sqs.change_message_visibility(
            QueueUrl=self._queue_url,
            ReceiptHandle=self._raw["ReceiptHandle"],
            VisibilityTimeout=seconds,
        )


class SQSMessageConsumer:
    def __init__(self, session: aioboto3.Session, queue_url: str, endpoint_url: str | None = None):
        self._session = session
        self._queue_url = queue_url
        self._endpoint_url = endpoint_url
        self._sqs = None
        self._ctx = None

    async def __aenter__(self):
        kwargs = {"endpoint_url": self._endpoint_url} if self._endpoint_url else {}
        self._ctx = self._session.client("sqs", **kwargs)
        self._sqs = await self._ctx.__aenter__()
        return self

    async def __aexit__(self, *exc):
        await self._ctx.__aexit__(*exc)

    async def poll(self, max_messages: int, wait_seconds: int) -> list[Message]:
        response = await self._sqs.receive_message(
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=wait_seconds,
        )
        return [SQSMessage(self._sqs, self._queue_url, raw) for raw in response.get("Messages", [])]
```

Client reuse: `__aenter__` opens one `aioboto3` SQS client; every poll, ack, nack, and heartbeat runs on it. ADR-006 §1.

### Shared `SQSWorker` (`src/shared/events/worker.py`, new)

Verbatim port of the existing `SQSWorker` at `src/properties/entrypoints/worker.py` (commit `fd9152ddfe08`), retargeted to the port API:

```python
class SQSWorker:
    def __init__(
        self,
        consumer: MessageConsumer,
        router: EventRouter,
        context: dict,
        worker_name: str,
        use_heartbeat: bool = True,
        heartbeat_interval: int = 60,
        heartbeat_extension: int = 120,
        max_concurrency: int = 5,
        max_messages_per_poll: int = 10,
        drain_timeout: int = 30,
    ) -> None: ...

    async def run(self) -> None:
        async with self._consumer as consumer:
            while self._running:
                messages = await consumer.poll(
                    max_messages=self._max_messages_per_poll,
                    wait_seconds=20,
                )
                tasks = [asyncio.create_task(self._bounded_process(m)) for m in messages]
                self._in_flight = tasks
                await asyncio.gather(*tasks, return_exceptions=True)
                self._in_flight = []
            await self._drain()

    async def _process_message(self, msg: Message) -> None:
        # contextvars here are for LOGGING ONLY — they bind fields onto every structlog
        # emission inside this task. The handler itself receives the full DomainEvent
        # as an argument via _router.dispatch; it must NOT read these back via
        # structlog.contextvars.get_contextvars(). That would be smuggling data through
        # a logging library.
        clear_contextvars()
        bind_contextvars(
            worker=self._worker_name,
            message_id=msg.message_id,
            event_id=msg.event.event_id,
            event_type=msg.event.event_type,
        )
        heartbeat_task = (
            asyncio.create_task(self._heartbeat(msg))
            if self._use_heartbeat else None
        )
        start = time.monotonic()
        try:
            # EventRouter calls `await handler(msg.event, self._context)`.
            # Handler signature: (event: DomainEvent, context: Any) -> None.
            await self._router.dispatch(msg.event, self._context)
            elapsed = time.monotonic() - start
            log.info(f"{self._worker_name}_message_processed", processing_seconds=round(elapsed, 2), status="success")
            await msg.ack()
        except Exception as exc:
            elapsed = time.monotonic() - start
            log.exception(
                f"{self._worker_name}_message_error",
                processing_seconds=round(elapsed, 2),
                status="error",
                error_type=type(exc).__name__,
            )
            await msg.nack()
        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)
            clear_contextvars()
```

### EventRouter invocation signature

`EventRouter.dispatch(event: DomainEvent, context)` keeps the existing shape. **Inside `dispatch`, the handler is invoked as `await handler(event, context)` — passing the full `DomainEvent`, not `event.data`.** This is the only behavioural change to `src/shared/events/router.py` in this spec.

The three existing handler migrations:

```python
# Before — reads the payload dict directly
async def handle_property_created(data: dict, ctx) -> None:
    await ctx["property"].discover_amenities.execute(property_id=data["property_id"])

# After — same logic, reads from the envelope
async def handle_property_created(event: DomainEvent, ctx) -> None:
    await ctx["property"].discover_amenities.execute(property_id=event.data["property_id"])
```

`event.event_type`, `event.event_id`, and `event.occurred_at` become first-class on every handler — no contextvars smuggling required.

**Failure semantics** — one rule for every worker: **handler raises → worker nacks → SQS redelivers up to `maxReceiveCount` → message lands in the queue's DLQ.** Domain-event and command-queue workers share this exact behaviour. This is the single ack/nack contract enforced by the shared `SQSWorker`; there is no per-context parameterization.

See §Behaviour change below for how this differs from the current command-queue behaviour and why we're accepting the change.

### Behaviour change: command workers nack-on-error

**Today** (per-context ADR-006 workers at `src/properties/entrypoints/worker.py`, `src/screening/entrypoints/worker.py`, `src/contract_intelligence/entrypoints/worker.py`): an unhandled exception inside a command handler causes the `finally` block to `_delete_message` — the message is **ack'd and dropped**. The job's DB status (e.g. `FAILED`) is the only record that anything went wrong. Expected exceptions (`InvalidJobTransitionError`, `ExtractionJobNotFoundError`, etc.) are caught inside handlers and logged as warnings — same net result: message ack'd.

**After this spec**: the shared worker nacks on any unhandled exception. SQS redelivers up to `maxReceiveCount=5` times, then routes to the queue's DLQ. Expected exceptions handled inside handlers remain caught-and-logged (no change — those never reach the worker).

**Why this is an improvement**, not a regression:
- A bug that causes an unhandled exception today silently drops work. Under the new behaviour, the message retries 5 times (giving transient failures a chance) and then lands in a DLQ where an operator can inspect the payload and decide what to do. Observability goes up; silent data loss goes down.
- The DB-status path (`FAILED` job with retry endpoint) keeps working for **expected** failures — those are caught inside the handler and the handler returns normally, so the worker ack's. Nothing about that flow changes.
- Command-queue DLQs already exist for contract_intelligence (`sqs_contract_dlq_url`) and are in scope for the other command queues as part of this spec's infrastructure work. Every command queue lands with a DLQ + redrive policy.

**What operators see change**:
- If a command handler starts throwing unhandled exceptions in production, messages now accumulate in a DLQ rather than vanishing. Alerting on `ApproximateNumberOfMessagesVisible` on DLQs is the new signal to watch.
- Transient external-API failures (e.g. Reducto timeout) now cause up to 5 retries before the message gives up, instead of one attempt. This is already the domain-event worker's behaviour and matches ADR-006 intent.

### Event type versioning (`src/shared/events/types.py`, updated)

Every constant renamed with a `.v1` suffix:

```python
# --- Domain events (broadcast via SNS) ---

# Properties
PROPERTY_CREATED_V1 = "PROPERTY_CREATED.v1"
PROPERTY_UPDATED_V1 = "PROPERTY_UPDATED.v1"
PROPERTY_DELETED_V1 = "PROPERTY_DELETED.v1"

# Screening
APPLICANT_SCREENED_V1 = "APPLICANT_SCREENED.v1"

# Customer management
USER_REGISTERED_V1 = "USER_REGISTERED.v1"
SUBSCRIPTION_CREATED_V1 = "SUBSCRIPTION_CREATED.v1"
# ... etc

# --- Commands (point-to-point via SQS) ---

# Properties (existing, shape-of-envelope already canonical)
PROPERTY_EXTRACTION_REQUESTED_V1 = "PROPERTY_EXTRACTION_REQUESTED.v1"
BATCH_PROPERTY_EXTRACTION_REQUESTED_V1 = "BATCH_PROPERTY_EXTRACTION_REQUESTED.v1"

# Screening (new — these commands are published today as flat payloads; this spec moves them onto the canonical envelope)
APPLICANT_EXTRACTION_REQUESTED_V1 = "APPLICANT_EXTRACTION_REQUESTED.v1"
APPLICANT_SCREENING_REQUESTED_V1 = "APPLICANT_SCREENING_REQUESTED.v1"

# Contract intelligence (new — same story)
DOCUMENT_INGESTION_REQUESTED_V1 = "DOCUMENT_INGESTION_REQUESTED.v1"
DOCUMENT_ANALYSIS_REQUESTED_V1 = "DOCUMENT_ANALYSIS_REQUESTED.v1"
```

(Note: an earlier draft of this spec listed `DOCUMENT_DLQ_RETRY_V1`. Ground-truth
audit during implementation showed `source_document_service.retry_document` re-publishes
to the same ingestion queue as `upload_document` with the same payload shape — it's
not a distinct event type. Removed.)

**Events and commands live in the same module** and share the envelope + handler + worker infrastructure. The only real divergence is transport (`EventPublisher` via SNS vs `CommandPublisher` via direct SQS). A developer reading a handler can't tell which one fired it.

Constant names change too — `PROPERTY_CREATED` → `PROPERTY_CREATED_V1`. Every import site updates. One-time mechanical refactor.

### DomainEvent consolidation

Ground-truth audit of the three "duplicate" files reveals two are genuine duplicates and one is a separately-named concept:

**Delete entirely — genuine duplicates + dead code:**
- `src/properties/domain/events.py` (the base class + `PropertyExtractionRequested` + `BatchPropertyExtractionRequested`). Every call site changes to canonical `DomainEvent(...)` constructors.
- `src/customers/domain/events.py` — base class + 8 subclass events (`UserRegistered`, `SubscriptionCreated`, …, `MemberRoleChanged`). **Zero publish sites** in `src/` — entirely dead code, a relic of a pre-ADR-007 design. The accompanying dead stack (`src/customers/application/ports/event_bus.py`, `src/customers/adapters/inmemory/inmemory_event_bus.py`, `src/customers/adapters/queue/sqs_event_bus.py`) is deleted too.

**Rename — internal audit-log, not cross-context events:**
- `src/screening/domain/models/domain_event.py` holds what looked like a `DomainEvent` but is actually an internal event-sourcing / audit-log artifact. It's persisted via `EventRepository.save()` (`screening/application/services/{submission,extraction,screening}.py` call `_uow.events.save(event)`). It's never published to SQS/SNS — it's screening's own audit trail with its own schema (has `applicant_id`, `payload`, `id`, `created_at`; no `data` field).
  - **File renamed** to `src/screening/domain/models/audit_event.py`.
  - **Class renamed** `DomainEvent` → `ScreeningAuditEvent` (and the three subclasses keep their names since they're `ApplicantSubmitted` / `DocumentsExtracted` / `ApplicantScreened`, not duplicate names).
  - `grep -rn "class DomainEvent" src/` acceptance criterion is satisfied: only `src/shared/events/base.py:9` remains.

Every call site of the deleted subclass-style events (grep for `PropertyExtractionRequested(`, `BatchPropertyExtractionRequested(`, etc.) changes to:

```python
# Before
event = PropertyExtractionRequested(job_id=str(job.id))

# After
event = DomainEvent(
    event_type=PROPERTY_EXTRACTION_REQUESTED_V1,
    data={"job_id": str(job.id)},
)
```

### Per-context worker CLI entrypoints

Each context gets (or keeps) one worker CLI per queue it consumes. The body of each CLI is ~20 lines: build the consumer, build the router, instantiate `SQSWorker`, await `run()`.

| Context | Queue | CLI file (new or updated) |
|---|---|---|
| `customers` | `customers-events-queue` (new) | `src/customers/entrypoints/worker.py` (**exists — rewritten**; points at the new per-context queue instead of the shared one) |
| `bookings` | `bookings-events-queue` (new) | `src/bookings/entrypoints/events_worker.py` (new) |
| `properties` (domain events consumer) | `properties-events-queue` (new) | `src/properties/entrypoints/events_worker.py` (new — distinct from the existing extraction worker) |
| `properties` (extraction command queue) | existing extraction queue | `src/properties/entrypoints/worker.py` — **refactored** to instantiate shared `SQSWorker` instead of its own class |
| `screening` (command queues) | existing | `src/screening/entrypoints/worker.py` — refactored the same way |
| `contract_intelligence` (command queues) | existing | `src/contract_intelligence/entrypoints/worker.py` — refactored the same way |
| Legacy shared events worker | `sqs_domain_events_queue` | **deleted** — `src/shared/entrypoints/events_worker.py` removed |

Concretely, for the command-queue workers, the per-context `SQSWorker` class is deleted and the CLI uses `from shared.events.worker import SQSWorker`. The old `processor=extraction_processor` module argument is replaced by an `EventRouter` with one handler registered per event type. **One pattern, everywhere — no `SingleHandlerAdapter`, no bifurcated `SQSWorker` interface, no special cases for command queues vs. domain events.**

### Command-queue processor split

Audit of existing processors:

| Processor module | Event types handled today | Action |
|---|---|---|
| `src/properties/adapters/workers/extraction_processor.py` | `PropertyExtractionRequested`, `BatchPropertyExtractionRequested` | **Split** into two handlers (the only real change — see example below) |
| `src/properties/adapters/workers/discovery_processor.py` | `PROPERTY_CREATED` (single) | Rename function, expose as handler, register one line |
| `src/screening/adapters/workers/extraction_processor.py` | single event type | Rename/expose, register |
| `src/screening/adapters/workers/screening_processor.py` | single event type | Rename/expose, register |
| `src/contract_intelligence/adapters/workers/ingestion_processor.py` | single event type | Rename/expose, register |
| `src/contract_intelligence/adapters/workers/analysis_processor.py` | single event type | Rename/expose, register |
| `src/contract_intelligence/adapters/workers/dlq_processor.py` | single event type | Rename/expose, register |

Only one file requires a real split. For that file:

```python
# Before (src/properties/adapters/workers/extraction_processor.py):
async def process_event(body: dict, container: Container) -> None:
    event_type = body.get("event_type")
    data = body.get("data", {})
    job_id = data.get("job_id")
    if event_type == "PropertyExtractionRequested":
        if not job_id: return log.warning("extraction.missing_job_id", body=body)
        try: await container.process_property_extraction.execute(job_id=job_id)
        except (InvalidJobTransitionError, ExtractionJobNotFoundError) as exc: ...
    elif event_type == "BatchPropertyExtractionRequested":
        if not job_id: return log.warning("batch_extraction.missing_job_id", body=body)
        try: await container.process_batch_property_extraction.execute(job_id=job_id)
        except (InvalidJobTransitionError, ExtractionJobNotFoundError) as exc: ...
    else:
        log.warning("extraction.unknown_event_type", event_type=event_type)

# After (same file):
async def handle_property_extraction_requested(event: DomainEvent, container: Container) -> None:
    job_id = event.data.get("job_id")
    if not job_id: return log.warning("extraction.missing_job_id", event_id=event.event_id)
    try: await container.process_property_extraction.execute(job_id=job_id)
    except (InvalidJobTransitionError, ExtractionJobNotFoundError) as exc: ...

async def handle_batch_property_extraction_requested(event: DomainEvent, container: Container) -> None:
    job_id = event.data.get("job_id")
    if not job_id: return log.warning("batch_extraction.missing_job_id", event_id=event.event_id)
    try: await container.process_batch_property_extraction.execute(job_id=job_id)
    except (InvalidJobTransitionError, ExtractionJobNotFoundError) as exc: ...
```

The CLI registers both on the router:

```python
router = EventRouter()
router.on(PROPERTY_EXTRACTION_REQUESTED_V1, handle_property_extraction_requested)
router.on(BATCH_PROPERTY_EXTRACTION_REQUESTED_V1, handle_batch_property_extraction_requested)
```

The `if/elif/else log.warning("unknown_event_type")` branch disappears — `EventRouter.dispatch` already emits `no_handler_for_event` (`src/shared/events/router.py:23-25`).

For the other six single-event-type processors, the existing function is already shaped like a handler; rename its parameters to `(event: DomainEvent, container)`, register on the router with one line.

### Handler re-registration

Every `router.on(EVENT, handler)` registration that today lives in `src/shared/entrypoints/events_worker.py:_build_router()` moves into the destination context's worker CLI. Example:

**Before** (`src/shared/entrypoints/events_worker.py`):
```python
router.on(APPLICANT_SCREENED, cm_handle_applicant_screened)   # customer_management context
router.on(APPLICANT_SCREENED, handle_applicant_screened)      # booking_management context
router.on(PROPERTY_CREATED, handle_property_created)          # properties context
```

**After**:
- `src/customers/entrypoints/worker.py` (existing file, rewritten) registers `cm_handle_applicant_screened` on its local router for `APPLICANT_SCREENED_V1`. The customers SQS queue is subscribed to the `APPLICANT_SCREENED.v1` SNS topic.
- `src/bookings/entrypoints/events_worker.py` (new) registers its handler similarly. Its queue is also subscribed to the same SNS topic.
- `src/properties/entrypoints/events_worker.py` (new) registers `handle_property_created`. Its queue is subscribed to `PROPERTY_CREATED.v1`.

Every handler that used to fan out in-process now fans out at the broker layer.

### Settings

New fields in `src/shared/config.py`:

```python
# --- Domain events (SNS fan-out) ---
sns_domain_events_topic_arn_prefix: str = ""        # e.g. "arn:aws:sns:eu-west-1:123:domain-events-"
sqs_customers_events_queue_url: str = ""
sqs_customers_events_dlq_url: str = ""
sqs_bookings_events_queue_url: str = ""
sqs_bookings_events_dlq_url: str = ""
sqs_properties_events_queue_url: str = ""
sqs_properties_events_dlq_url: str = ""
# (screening, contract_intelligence events queues already exist for their command workers;
#  keep them, add _events_ variants as new context-domain-event queues if needed)

# --- Command queues (new DLQs required to honour the §Behaviour change promise) ---
# These command queues already exist today; their DLQs are NEW.
sqs_property_extraction_dlq_url: str = ""
sqs_applicant_extraction_dlq_url: str = ""
sqs_applicant_screening_dlq_url: str = ""
# (sqs_contract_ingestion_dlq_url and sqs_contract_analysis_dlq_url already exist
#  in src/shared/config.py:60-61 — no change for contract_intelligence command queues.)
```

Remove (when cutover completes):
- `sqs_domain_events_queue_url` (legacy shared queue).

### Infrastructure (coordinate with IaC — out of this repo)

Required before the foundation spec can ship:

**Domain-event side (SNS fan-out):**
- SNS topic per event type. Naming convention: `domain-events-${EVENT_TYPE_WITH_DOTS_REPLACED_BY_DASHES}`. Examples: `domain-events-PROPERTY_CREATED-v1`, `domain-events-APPLICANT_SCREENED-v1`, `domain-events-USER_REGISTERED-v1`. One per domain-event type listed in `src/shared/events/types.py`.
- One SQS queue per consuming context (customers-events, bookings-events, properties-events), plus a DLQ, plus a redrive policy with `maxReceiveCount=5`.
- SNS→SQS subscriptions, one per (context × event_type) pair the context handles. `RawMessageDelivery` is left at its **default (`false`)** — SNS wraps the payload. `SQSMessage` unwraps the SNS envelope in `__init__`.

**Command-queue side (direct SQS):**
- Every command queue gets a DLQ + redrive policy with `maxReceiveCount=5` — required by §Behaviour change. Concretely:
  - `sqs_property_extraction_queue_url` → **new** DLQ `sqs_property_extraction_dlq_url`.
  - `sqs_applicant_extraction_queue_url` → **new** DLQ `sqs_applicant_extraction_dlq_url`.
  - `sqs_applicant_screening_queue_url` → **new** DLQ `sqs_applicant_screening_dlq_url`.
  - `sqs_contract_ingestion_queue_url` → DLQ `sqs_contract_ingestion_dlq_url` **already exists**.
  - `sqs_contract_analysis_queue_url` → DLQ `sqs_contract_analysis_dlq_url` **already exists**.

**IAM (both):**
- Each context's EC2/Fargate role needs `sqs:ReceiveMessage` / `DeleteMessage` / `ChangeMessageVisibility` on its queues (both domain-event + command queues it consumes), plus `sns:Publish` on every domain-event topic its write side publishes to, plus `sqs:SendMessage` on every command queue its write side publishes to.

Document the naming convention here so the IaC PR is a mechanical follow.

### Rollout

This is an **atomic release**. Every publisher and every consumer ships in the same monorepo deploy:

1. **IaC PR lands first.** Provisions SNS topics, per-context domain-event SQS queues + DLQs, the three new command-queue DLQs (`sqs_property_extraction_dlq_url`, `sqs_applicant_extraction_dlq_url`, `sqs_applicant_screening_dlq_url`) with redrive policies attached to their source queues, subscriptions, IAM. No-op in production until the app release — the old `sqs_domain_events_queue` keeps serving.
2. **Single monorepo release** switches, in one deploy:
   - **Domain-event publishers**: `SQSDomainEventPublisher` → `SNSEventPublisher`.
   - **Domain-event consumers**: shared `sqs_domain_events_queue` → per-context queues.
   - **Command publishers**: per-context `SQSMessagePublisher` → shared `SQSCommandPublisher` with canonical `DomainEvent` envelopes (flat-payload publishes are replaced with `DomainEvent(event_type=X_V1, data={...})`).
   - **Command consumers (all command-queue workers)**: per-context `SQSWorker` classes → shared `SQSWorker` + `EventRouter`. Handler signatures change from `process_event(body, container)` to `handle_<event_type>(event: DomainEvent, container)`.

   Every context ships together; there is no partial state across release boundaries. A partial rollout (e.g. command publishers updated but command consumers still on flat payloads) would silently break every command queue — that's why the deploy is atomic.
3. **Legacy `sqs_domain_events_queue` is drained and deleted one week after cutover.** The queue's depth is monitored during that week; zero residual messages = safe to remove.

**Dual-publish is explicitly NOT used.** Publishers do not write to both the legacy queue and SNS during a transition window. Rationale: (a) the monorepo deploys every context simultaneously, so there is no cross-release-boundary partial state to protect against; (b) dual-publish adds complexity and its own ordering bugs; (c) rollback is clean — revert the release commit and publishers/consumers revert to the legacy queue with no code changes beyond the git revert, because the IaC PR doesn't remove the legacy queue.

Rollback criterion: if post-deploy a critical handler is silently skipping events, revert the release commit; the legacy queue resumes absorbing publishes on the next worker boot.

### LocalStack tests

LocalStack supports both SNS and SQS with `SNS → SQS` subscriptions. The test fixtures (one `testcontainers/localstack` per session, following `tests/e2e/test_notification_flow.py`) provision topics, queues, and subscriptions at test setup.

## Affected files / surfaces

**New files:**
- `src/shared/events/ports.py` — `EventPublisher`, `CommandPublisher`, `Message`, `MessageConsumer` Protocols.
- `src/shared/events/worker.py` — the shared `SQSWorker` class, plus `_heartbeat` helper.
- `src/shared/events/adapters/sns_event_publisher.py` — `SNSEventPublisher` with dot→dash topic translation (domain events via SNS fan-out).
- `src/shared/events/adapters/sqs_command_publisher.py` — `SQSCommandPublisher`, replaces both per-context `SQSMessagePublisher` classes (commands via direct SQS).
- `src/shared/events/adapters/sqs_message_consumer.py` — `SQSMessageConsumer` + `SQSMessage` (unwraps the SNS envelope when present; plain envelope when delivered directly by a command publisher).
- `src/shared/events/adapters/inmemory_event_bus.py` — in-memory pub/sub for tests. Replaces the ad-hoc `PropertyInMemoryEventBus` and `InMemoryEventBus` variants in other contexts. Also provides an in-memory `CommandPublisher` test double.
- `src/bookings/entrypoints/events_worker.py` — new CLI, consumes bookings-events-queue. (Bookings has no worker CLI today, only a Lambda.)
- `src/properties/entrypoints/events_worker.py` — new CLI, consumes properties-events-queue (distinct from the existing extraction CLI at `src/properties/entrypoints/worker.py`).

**Updated files:**
- `src/shared/events/types.py` — every constant renamed to its `.v1` form (`PROPERTY_CREATED` → `PROPERTY_CREATED_V1 = "PROPERTY_CREATED.v1"` etc.).
- `src/shared/events/base.py` — unchanged code; becomes the only `DomainEvent` class in the repo.
- `src/shared/events/router.py` — `dispatch()` invokes handlers as `await handler(event, context)` (was `event.data`). No other changes.
- `src/shared/events/publisher.py` — `DomainEventPublisher` ABC removed (replaced by `EventPublisher` Protocol in `ports.py`).
- `src/shared/events/__init__.py` — `__all__` updated: `DomainEventPublisher` removed, `EventPublisher` + `Message` + `MessageConsumer` added.
- `src/shared/config.py` — new Settings fields:
  - Domain-event side: `sns_domain_events_topic_arn_prefix`, `sqs_customers_events_queue_url` + `_dlq_url`, `sqs_bookings_events_queue_url` + `_dlq_url`, `sqs_properties_events_queue_url` + `_dlq_url`.
  - Command-queue side (DLQs newly required by §Behaviour change): `sqs_property_extraction_dlq_url`, `sqs_applicant_extraction_dlq_url`, `sqs_applicant_screening_dlq_url`. The existing `sqs_contract_ingestion_dlq_url` + `sqs_contract_analysis_dlq_url` stay as-is.
  - `sqs_domain_events_queue_url` removed at the end of the cutover week per §Rollout.
- `src/properties/entrypoints/worker.py` — refactor to use shared `SQSWorker` + an `EventRouter` (two handlers registered after the Option-2 split: `PROPERTY_EXTRACTION_REQUESTED_V1` and `BATCH_PROPERTY_EXTRACTION_REQUESTED_V1`). External CLI and queue URL unchanged.
- `src/screening/entrypoints/worker.py` — refactor to use shared `SQSWorker` + an `EventRouter` (one handler per sub-CLI: extraction, screening).
- `src/contract_intelligence/entrypoints/worker.py` — refactor to use shared `SQSWorker` + an `EventRouter` (one handler per sub-CLI: ingestion, analysis, dlq).
- `src/customers/entrypoints/worker.py` — **exists** (runs the current `EventsWorker` over the shared queue). Rewritten to instantiate the shared `SQSWorker` pointed at the new customers-events-queue. CLI arg rename: `--queue events` stays; queue URL changes from `sqs_domain_events_queue_url` to `sqs_customers_events_queue_url`.
- Every handler signature — the three existing handlers (`cm_handle_applicant_screened` in `src/customers/adapters/workers/event_processor.py`, `handle_applicant_screened` in `src/bookings/adapters/events/handlers.py`, `handle_property_created` in `src/properties/adapters/workers/discovery_processor.py`) migrate from `(data: dict, ctx)` to `(event: DomainEvent, ctx)`.
- Every **domain-event** publish site — update event type constants and (where the publish uses subclass-style events) rewrite to plain `DomainEvent(event_type=PROPERTY_EXTRACTION_REQUESTED_V1, data={...})`. Sites identified by grep:
  - `src/properties/application/use_cases/create_property.py`
  - `src/properties/application/use_cases/process_property_extraction.py`
  - `src/properties/adapters/api/routes/property_amenities.py` (inline publish from a route)
  - `src/screening/application/services/screening.py` — verified canonical (`data=screened_event.model_dump(mode="json")` at line 151). Only the event_type string needs the `.v1` suffix.
  - `src/screening/application/events.py` — **delete** the `event_type` default (line 23) from `ApplicantScreenedEvent`. The envelope is the single source of truth for event_type; the Pydantic payload model shouldn't redundantly declare it. Drops the "two sources of truth in lock-step" risk.
  - `src/bookings/adapters/events/handlers.py`
- Every **command** publish site — rewrite to use the new `CommandPublisher.send(queue_url, event)` port with a canonical `DomainEvent` envelope instead of the legacy `SQSMessagePublisher.publish(queue_url, raw_dict)`. Sites identified by grep:
  - `src/screening/application/services/submission.py:172-173` — enqueues applicant extraction. New: `DomainEvent(event_type=APPLICANT_EXTRACTION_REQUESTED_V1, data={"applicant_id": str(applicant_id), ...})`.
  - `src/screening/application/services/extraction.py:96-97` — enqueues applicant screening. New: `APPLICANT_SCREENING_REQUESTED_V1`.
  - `src/contract_intelligence/application/services/ingestion_service.py:134` — enqueues downstream analysis. New: `DOCUMENT_ANALYSIS_REQUESTED_V1`.
  - `src/contract_intelligence/application/services/source_document_service.py:73` — enqueues ingestion on upload. New: `DOCUMENT_INGESTION_REQUESTED_V1`.
  - `src/contract_intelligence/application/services/source_document_service.py:172` — re-enqueues a FAILED document for re-ingestion. New: `DOCUMENT_INGESTION_REQUESTED_V1` (same event type as the fresh-upload path — see note under §Event type versioning).
  - `src/properties/application/use_cases/submit_property_extraction.py:61`, `submit_batch_property_extraction.py:61`, `retry_extraction_job.py:47-49` — properties also has its own command publisher (`SQSEventBus` + `EventBus` port + `InMemoryEventBus` adapter) that predates ADR-008 and uses raw `boto3.client.send_message`. Migrate all three publish sites to use the shared `CommandPublisher.send(queue_url, event)` path. Delete `src/properties/application/ports/event_bus.py`, `src/properties/adapters/queue/sqs_event_bus.py`, and `src/properties/adapters/inmemory/inmemory_event_bus.py` — replaced by `shared.events.ports.CommandPublisher` + the shared adapters. Every publish site was already constructing canonical `DomainEvent` envelopes (Commit 2) — only the transport glue changes.
  - Application-service constructors rename: `publisher: SQSMessagePublisher` → `command_publisher: CommandPublisher`. Container wiring in `src/screening/container.py` + `src/contract_intelligence/container.py` + `src/properties/container.py` updates accordingly.
- Command-queue processor files — rewired per the "Command-queue processor split" table:
  - `src/properties/adapters/workers/extraction_processor.py` — **split** (2 handlers).
  - `src/properties/adapters/workers/discovery_processor.py` — rename parameters to `(event, ctx)`, expose as handler.
  - `src/screening/adapters/workers/extraction_processor.py`, `screening_processor.py` — same.
  - `src/contract_intelligence/adapters/workers/ingestion_processor.py`, `analysis_processor.py`, `dlq_processor.py` — same.
(Legacy `sqs_publisher.py` files moved to the Deleted section below — both their `SQSMessagePublisher` and `SQSMessageConsumer` classes are superseded by the new shared adapters.)
- `docker-compose.yml` — provision the new SNS topics + per-context SQS queues + subscriptions for local LocalStack dev. Without this, `uv run uvicorn` can publish but nothing consumes. Use a LocalStack init script (`docker-entrypoint-initaws.d/*.sh`) or the `SERVICES=sns,sqs` env + boot scripts.
- `tests/conftest.py` — every fixture that wires a `DomainEventPublisher` / `SQSDomainEventPublisher` / `PropertyInMemoryEventBus` migrates to the new `EventPublisher` Protocol + `InMemoryEventBus`. Also: worker fixtures for integration tests gain per-context queue setup against LocalStack.

**Deleted files:**
- `src/shared/entrypoints/events_worker.py` — legacy shared worker.
- `src/shared/entrypoints/lambda_events.py` — Lambda handler that imported from the legacy worker. Long-running per-context workers supersede it. (If any production path still depends on it, surface during implementation and migrate instead.)
- `src/shared/adapters/sqs_event_publisher.py` — replaced by `src/shared/events/adapters/sns_event_publisher.py`.
- `src/screening/adapters/queue/sqs_publisher.py` — contains legacy `SQSMessagePublisher` + `SQSMessageConsumer`; both superseded by `src/shared/events/adapters/sqs_command_publisher.py` and `src/shared/events/adapters/sqs_message_consumer.py`.
- `src/screening/application/ports/messaging.py` — legacy `MessagePublisher` + `MessageConsumer` ABCs; replaced by the shared `CommandPublisher` / `MessageConsumer` Protocols.
- `src/contract_intelligence/adapters/queue/sqs_publisher.py` — same fate.
- `src/contract_intelligence/application/ports/messaging.py` — legacy `MessagePublisherPort` ABC; replaced by the shared `CommandPublisher` Protocol.
- `src/properties/application/ports/event_bus.py` — legacy properties-specific `EventBus` ABC; replaced by the shared `CommandPublisher` Protocol.
- `src/properties/adapters/queue/sqs_event_bus.py` — legacy `SQSEventBus` using sync boto3; replaced by the shared `SQSCommandPublisher`.
- `src/properties/adapters/inmemory/inmemory_event_bus.py` — legacy test double; replaced by `shared.events.adapters.inmemory_event_bus.InMemoryCommandPublisher`.
- `src/properties/domain/events.py` — subclass-based duplicate (`DomainEvent` + `PropertyExtractionRequested` + `BatchPropertyExtractionRequested`). Call sites rewritten to plain `DomainEvent(event_type=..., data=...)`.
- `src/customers/domain/events.py` — subclass-based duplicate. **Dead stack**: also delete `src/customers/application/ports/event_bus.py`, `src/customers/adapters/inmemory/inmemory_event_bus.py`, `src/customers/adapters/queue/sqs_event_bus.py` (no production code references them).
- `src/screening/domain/models/domain_event.py` — **renamed**, not deleted (see §DomainEvent consolidation). Moved to `audit_event.py`; class `DomainEvent` → `ScreeningAuditEvent`. The file serves the internal audit-log concept, not cross-context events.
- `src/customers/adapters/workers/events_worker.py` — per-context `EventsWorker` variant; replaced by the shared `SQSWorker`.
- `src/customers/adapters/queue/sqs_consumer.py` — per-context `SQSMessageConsumer` variant; replaced by the shared one.
- `src/customers/entrypoints/lambda_events.py` — event Lambda, superseded by `customers/entrypoints/worker.py`. Its sole import (`customers.adapters.workers.event_processor.process_event`) was renamed in Commit 4+5.
- `src/bookings/entrypoints/lambda_applicant_screened.py` — Lambda handler that hard-codes the legacy `"APPLICANT_SCREENED"` string. Superseded by `src/bookings/entrypoints/events_worker.py`.
- (`src/customers/entrypoints/lambda_handler.py` was previously listed here — **spec correction**: that file is the HTTP/Mangum adapter (re-exports `app, handler` from `shared.entrypoints.lambda_handler`), not an event Lambda. Kept.)

**Note on Lambda deletion:** the four Lambda entrypoints above are the default-delete choice for this spec. If any is load-bearing in production (check with whoever owns deployment), migrate instead — update the hard-coded event type string to the `.v1` form, point at the new per-context SQS queue, and leave the Lambda infrastructure alone. Flagged in `Open questions` below so the user can override during implementation.

**Tests:**
- Unit tests for `SQSWorker` (ack on success, nack on failure, heartbeat extension during long handlers, graceful drain).
- Unit tests for `SQSMessageConsumer` and `SQSMessage` (SNS→SQS envelope unwrapping).
- Integration test against LocalStack: publish one event to an SNS topic; two context queues subscribed; assert both workers receive it; one handler raises; assert that queue's message appears in the DLQ after `maxReceiveCount`, the other queue's message processes successfully. This is the proof that handler isolation works.
- Every existing test that references a deleted event type subclass or the legacy `DomainEventsWorker` updates to the new constants / the shared worker.

## Acceptance criteria

- [ ] `src/shared/events/ports.py` defines `EventPublisher`, `CommandPublisher`, `Message`, `MessageConsumer` as Protocols.
- [ ] `src/shared/events/adapters/sqs_command_publisher.py:SQSCommandPublisher` exists and implements `CommandPublisher.send(queue_url, event) -> None` via `sqs.send_message(QueueUrl=queue_url, MessageBody=event.to_json())`.
- [ ] `src/shared/events/worker.py` contains the single ADR-006-compliant `SQSWorker` class, with client reuse, heartbeat, batch polling, bounded concurrency, structured logging via contextvars (for logs only), drain, and nack-on-error for every worker (handler raises → worker nacks → SQS redelivers → DLQ, per §Failure semantics).
- [ ] **Handlers are invoked as `(event: DomainEvent, context) -> None`.** The three existing domain-event handlers (`cm_handle_applicant_screened`, `handle_applicant_screened`, `handle_property_created`) are migrated. The split command-queue handlers (`handle_property_extraction_requested`, `handle_batch_property_extraction_requested`, plus six renamed single-event-type handlers in `discovery_processor.py`, screening/ingestion/analysis/dlq processors) follow the same signature. Handler code reads `event.event_type`, `event.event_id`, `event.occurred_at` directly from the argument — `grep -r "structlog.contextvars.get_contextvars" src/` returns **zero hits in handler code** (worker-internal bindings are allowed).
- [ ] **Command-queue processors are split per the table in §"Command-queue processor split".** `src/properties/adapters/workers/extraction_processor.py` no longer contains `process_event` with internal `if event_type ==` branching; instead it exports `handle_property_extraction_requested` + `handle_batch_property_extraction_requested`. Every other processor module exports exactly one handler function named `handle_<event_type>` with signature `(event: DomainEvent, container) -> None`. `grep -rn "def process_event" src/` returns zero hits.
- [ ] **Every publish site — events AND commands — emits the canonical envelope.** A new unit test at `tests/unit/test_canonical_envelope.py` constructs each production publish call with a stubbed `EventPublisher` / `CommandPublisher`, captures the published `DomainEvent`, and asserts `event.data` is non-empty and contains the fields the corresponding handler reads. Explicitly covers:
  - Domain-event publishers: `src/screening/application/services/screening.py:148-153` (canonical today, regression-guarded), every property-context publisher.
  - Command publishers (migrated by this spec): `src/screening/application/services/submission.py:172-173`, `src/screening/application/services/extraction.py:96-97`, `src/contract_intelligence/application/services/ingestion_service.py:134`, `src/contract_intelligence/application/services/source_document_service.py:73,172`.
  - `grep -rn "sqs.send_message" src/` outside of `src/shared/events/adapters/` returns zero hits (enforces that all publishes go through `EventPublisher` / `CommandPublisher`, not raw SQS).
  - `grep -rn "class SQSMessagePublisher" src/` returns zero hits (the per-context command publishers are deleted).
- [ ] **`SNSEventPublisher.publish(event)` resolves the topic ARN by replacing dots in `event.event_type` with dashes.** A unit test exercises the mapping table above (PROPERTY_CREATED.v1 → domain-events-PROPERTY_CREATED-v1). A LocalStack integration test creates the topic under the dash name and round-trips a real event.
- [ ] `src/shared/events/adapters/sns_event_publisher.py` and `sqs_message_consumer.py` exist and round-trip a `DomainEvent` through a real SNS→SQS pipe in the LocalStack integration test. `SQSMessage.__init__` unwraps the SNS envelope correctly (JSON within JSON).
- [ ] The three duplicate `DomainEvent` classes are deleted. `grep -rn "class DomainEvent" src/` returns only `src/shared/events/base.py`.
- [ ] The four non-shared worker classes are deleted. `grep -rn "class SQSWorker\|class EventsWorker\|class DomainEventsWorker" src/` returns only `src/shared/events/worker.py:SQSWorker`.
- [ ] The three per-context `SQSMessageConsumer` duplicates are deleted. `grep -rn "class SQSMessageConsumer" src/` returns only `src/shared/events/adapters/sqs_message_consumer.py`.
- [ ] `src/shared/entrypoints/events_worker.py` is deleted. Handler registrations moved to per-context worker CLIs.
- [ ] The three event-handler Lambda entrypoints (`src/shared/entrypoints/lambda_events.py`, `src/bookings/entrypoints/lambda_applicant_screened.py`, `src/customers/entrypoints/lambda_events.py`) are **either deleted or migrated** — `grep -rn 'event_type.*APPLICANT_SCREENED"' src/` must not find the un-suffixed legacy string in any surviving Lambda. The HTTP/Mangum adapter at `src/customers/entrypoints/lambda_handler.py` is kept (not an event Lambda).
- [ ] Every event type constant in `src/shared/events/types.py` has the `_V1` Python name and `.v1` string value. Every import site renamed; every publish site updated.
- [ ] Every domain-event-consuming context has its own worker CLI owning a distinct SQS queue with a DLQ + `maxReceiveCount=5` redrive policy. Specifically:
  - `python -m bookings.entrypoints.events_worker` (new file)
  - `python -m customers.entrypoints.worker --queue events` (existing file, rewritten — `--queue events` stays for backwards compatibility; file kept at `worker.py` to minimise churn)
  - `python -m properties.entrypoints.events_worker` (new file, distinct from `properties.entrypoints.worker` which is the command-queue extraction CLI)
  Verified via LocalStack fixture.
- [ ] **Handler isolation test** (integration, LocalStack): two context queues subscribed to the same SNS topic; one handler raises on every message; the other handler succeeds on every message. After `maxReceiveCount` retries, the failing queue's message is in its DLQ; the succeeding queue's DLQ is empty; the succeeding queue's message is ack'd.
- [ ] **Cross-context fan-out test** (integration, LocalStack): a single `SNSEventPublisher.publish(event)` call produces one message in each of the two subscribed queues.
- [ ] **Command-queue worker smoke test** (new, integration): for each of `properties extraction`, `screening screening`, `screening extraction`, `contract_intelligence ingestion`, `contract_intelligence analysis`, `contract_intelligence dlq` — start the CLI against a LocalStack queue, publish one canonical `DomainEvent` via `SQSCommandPublisher.send(queue_url, event)`, observe the message is processed and ack'd (or moved to DLQ where applicable — the dlq sub-CLI ack's instead of nacking because it IS the DLQ), send SIGTERM, observe clean shutdown. Lives in `tests/integration/test_worker_smoke.py` (new).
- [ ] **Command-queue DLQ test** (new, integration): for one representative command-queue worker (e.g. `properties extraction`), configure LocalStack with `maxReceiveCount=5` redrive policy, monkeypatch the handler to raise an unhandled `RuntimeError` on every invocation, publish one canonical `DomainEvent` via `SQSCommandPublisher.send(queue_url, event)`, observe exactly 5 delivery attempts, assert the message lands in the DLQ, assert the source queue is empty. Separately, publish an event that triggers an **expected** exception inside the handler (e.g. `InvalidJobTransitionError` caught-and-logged) and assert the message is ack'd after one attempt — proving the DB-status path still works. Lives alongside the smoke test in `tests/integration/test_worker_smoke.py`.
- [ ] `docker-compose.yml` provisions the new SNS topics + per-context SQS queues + subscriptions via LocalStack init scripts. `docker compose up -d && uv run python -m properties.entrypoints.events_worker --queue events` runs without config errors.
- [ ] `tests/conftest.py` fixture updates land: `InMemoryEventBus` replaces the per-context variants; `EventPublisher` replaces `DomainEventPublisher` in every fixture; integration-test fixtures provision per-context queues.
- [ ] Every existing handler / route / use-case test passes after the constant / signature rename.

## Open questions

One user-confirmation needed before implementation; two cosmetic implementation-time picks.

**Resolved (2026-04-17, at `/spec-implement` time):**

- ~~Lambda entrypoints: delete or migrate?~~ → **Delete the three event-handler Lambdas.** Confirmed by the owner; no production deployment currently routes event traffic through Lambda. Files deleted: `src/shared/entrypoints/lambda_events.py`, `src/bookings/entrypoints/lambda_applicant_screened.py`, `src/customers/entrypoints/lambda_events.py`. **Correction during implementation:** `src/customers/entrypoints/lambda_handler.py` was originally on the deletion list but is the HTTP/Mangum adapter (FastAPI → Lambda) for the HTTP API, not an event Lambda. Kept.

**Implementation-time picks (cosmetic):**

- Whether `EventRouter` stays in `src/shared/events/router.py` or moves into `src/shared/events/worker.py`. Purely file layout.
- Whether the SNS topic ARN prefix is a single Settings field (clean) or resolved from a dict map per event type (flexible). Default to the single prefix; move to a map only if a per-topic exception appears.

## Deviations captured during implementation

- **Contract-intelligence DLQ sub-command**: the original CLI had `--queue dlq` referencing `settings.sqs_contract_dlq_url`, which never existed on `Settings` (only `sqs_contract_ingestion_dlq_url` + `sqs_contract_analysis_dlq_url` exist). That was dead/broken code. Replaced with two sub-commands `--queue ingestion-dlq` and `--queue analysis-dlq`, each pointed at the real DLQ setting.

## Out of scope follow-ups

- RabbitMQ / Kafka adapter. The ports are designed for them; implementation is a separate spec when we have the business need.
- Transactional outbox. Separate ADR when we start losing publishes.
- Event schema registry + JSON-Schema runtime validation.
- Per-event-type retention configuration.
- Extracting this infrastructure to a shared pypi package for other repos.
