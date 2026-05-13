# RabbitMQ transport adapter

**Status:** shipped
**Owner:** Peter
**Created:** 2026-05-13

## Problem

The event bus uses SNS for fan-out and SQS for both broadcast subscriptions and point-to-point commands. The single-tenant Coolify deploy doesn't justify running AWS SNS+SQS: cost, ops, network egress, and IAM surface area. We want a self-hostable transport that runs alongside the rest of the stack (Postgres, Redis, S3, …).

ADR-008's port-and-adapter design was explicitly built to absorb this swap (`src/shared/events/ports.py:1-10`):

> Handler code depends on these ports only; swapping SQS+SNS for RabbitMQ or Kafka is an adapter change.

This spec adds the swap surface and a switch. It does **not** change which transport runs in prod yet (that's `2026-05-coolify-compose-prod`'s job).

## Goal

Three new adapters in `src/shared/events/adapters/` implementing the existing four Protocol ports against RabbitMQ via `aio-pika`. `src/shared/entrypoints/bootstrap.py` swaps its imports from `SNSEventPublisher` / `SQSCommandPublisher` / `SQSMessageConsumer` to the three RabbitMQ peers — no runtime flag, no conditional wiring; the swap is decided at code-write time. SNS+SQS adapter files stay in the repo (per the "don't delete" directive) but no production code path imports them after this spec. Dev compose moves LocalStack to S3-only and adds a RabbitMQ service so dev matches prod.

## Non-goals

- **Removing SNS / SQS adapter code.** All three retained as dead code (per the "don't delete" directive); no production import path references them after this spec. Their unit tests keep passing since the classes still work in isolation.
- **A runtime `EVENT_BUS_BACKEND` flag.** Decided against — the cutover is one-way; carrying a switch is dead complexity. If we ever need SNS+SQS again, we revert the import swap.
- **Flipping prod to RabbitMQ.** Handled by `2026-05-coolify-compose-prod`.
- **Changing the four Protocols** in `src/shared/events/ports.py`. The whole point is that the port surface is correct as-is.
- **RabbitMQ clustering / HA.** Single-node container, persistent volume.
- **Pre-declaring exchanges + queues** via Terraform / init container. Consumer-side idempotent declares.

## Approach

### 1. New adapters

`src/shared/events/adapters/`:

- **`rabbitmq_event_publisher.py`** — `RabbitMQEventPublisher.publish(event)`:
  - Publishes to the topic exchange (default `domain-events`) with routing-key = `event.event_type` (e.g. `PROPERTY_CREATED.v1`).
  - AMQP `message_id` property = `event.event_id`.
  - `delivery_mode=DeliveryMode.PERSISTENT` (=2) — message survives broker restart in a durable queue.
  - **Each `publish()` opens a fresh channel with `publisher_confirms=True`**, awaits the broker `basic.ack`, then closes the channel. Channel-per-publish isolates channel-level errors (see §3(f)). Matches SNS's "durable once `publish` returns" guarantee. See §3(a).
  - Topic-exchange analogue of ADR-008's "one SNS topic per event_type" pattern: subscribers bind queues with routing-key patterns instead of subscribing one queue per topic.

- **`rabbitmq_command_publisher.py`** — `RabbitMQCommandPublisher.send(queue_url, event)`:
  - Publishes to the default exchange (`""`) with routing-key = `queue_url` (interpreted as queue name).
  - AMQP `message_id` = `event.event_id`; `delivery_mode=2`; same channel-per-publish + `publisher_confirms=True` pattern as the event publisher (fresh channel per `send()`, closed on return).
  - **`mandatory=True`** — if no queue is bound to the routing key (typo in `queue_url`, queue not declared yet), the broker returns the message with `basic.return` and the adapter raises `aio_pika.exceptions.DeliveryError`. Catches the most common silent-failure mode of AMQP. See §3(a).
  - Param name `queue_url` kept for port-compatibility; in RabbitMQ-land it's the queue name.

- **`rabbitmq_message_consumer.py`** — `RabbitMQMessageConsumer` + `RabbitMQMessage`:
  - Async context manager. `__aenter__` opens a channel on the per-process AMQP connection (passed into the constructor by the entrypoint), sets `basic.qos(prefetch_count=max_concurrency)` (=5), declares the queue (idempotent) with `x-queue-type=quorum` + `x-delivery-limit=5` + `x-dead-letter-exchange=domain-events-dlx`, and starts a background task draining `queue.iterator()` into an internal `asyncio.Queue` buffer of size `prefetch_count`. See §3(c)+(d).
  - `poll(max_messages, wait_seconds)` drains the buffer for up to `wait_seconds`. Returns up to `max_messages` `RabbitMQMessage` objects. Matches the SQS `poll()` contract.
  - `Message.ack` → `basic.ack`.
  - `Message.nack` → `basic.nack(requeue=true)`. Broker requeues; queue's `x-delivery-limit=5` caps redelivery; after 5th nack, broker routes to DLX. **Matches SQS `maxReceiveCount=5`** exactly — no behavior change vs. today.
  - `Message.message_id` returns the AMQP `message_id` property the publisher set (= `event.event_id`); falls back to the delivery tag only if absent (shouldn't happen post-spec).
  - `Message.extend_visibility` → **no-op**. RabbitMQ has no per-message visibility timeout. The broker's `consumer_timeout` (default 30 min) is the hard ceiling. The worker's `_heartbeat` helper (`worker.py:30-47`) stays in the file for SNS+SQS adapter unit tests, but worker entrypoints pass `use_heartbeat=False` to `EventBusWorker` after the swap so the heartbeat task never spawns on RabbitMQ (no point burning cycles calling a no-op every 60s).

Library: **`aio-pika`** — standard async-native Python AMQP client.

### 2. Exchange / queue topology

Declared idempotently on consumer `__aenter__` (and on first publish for publishers) — RabbitMQ `declare` is a no-op on existing resources. No separate init container.

- **`domain-events` topic exchange** (durable, persistent). Routing-key = `event.event_type`.
- **Per-context bound queues** — declared by the consumer on `__aenter__`, bound to `domain-events` with the routing-key patterns the context handles. Names mirror today's SQS queues:
  - `listings-events-queue` ← patterns `PROPERTY_*.v1`, `PROPERTY_LISTING_*.v1`
  - others added as contexts come online (`customers-events-queue`, `bookings-events-queue`, etc.)
- **Command queues** — declared directly (no exchange binding). Names mirror today's `SQS_*_QUEUE_URL` values:
  - `property-extraction-queue`, `property-enrichment-queue`, `applicant-extraction-queue`, `applicant-screening-queue`, `contract-ingestion-queue`, `contract-analysis-queue`.
- **Every queue declared with the SQS-equivalent retry profile:** `x-queue-type=quorum` + `x-delivery-limit=5` + `x-dead-letter-exchange=domain-events-dlx`. Quorum queues (RabbitMQ 3.8+) track per-message redelivery counts broker-side; after the 5th `basic.nack(requeue=true)` the broker auto-routes to the DLX. Direct equivalent of SQS `maxReceiveCount=5` semantics.
- **Single global DLX `domain-events-dlx`** (fanout). One bound queue `dead-letters` for ops inspection. The `x-death` header chain identifies origin queue, first-rejection timestamp, and redelivery count.

**Trade-off — quorum queues on a single-node deploy.** Quorum queues use Raft consensus to replicate. A single-node deploy has no peers, so consensus runs against itself: queues work in degraded mode but pay memory + write amplification per message. Classical alternative (classic queues + app-side delivery counter via headers + DLX/TTL loop) is brittle and would re-introduce app-side state we don't want. **Decision: keep quorum.** Broker-side `x-delivery-limit` is clean, the overhead is small at our volume, and we get a future-proof path to HA without code changes when traffic justifies a second node.

**Routing-key wildcard discipline.** Topic exchanges fan out by pattern match, so a new event type that incidentally matches an existing binding (`PROPERTY_INTERNAL_DEBUG.v1` against a `PROPERTY_*.v1` subscription) silently lands in queues that didn't intend to receive it. SNS's exact-topic-ARN model didn't have this hazard. **Discipline: when adding a new event_type, grep every `bind` call for matching patterns and confirm each subscriber's handler is event_type-aware.**

### 3. Reliability primitives (the SQS-parity surface)

SNS+SQS gets durability + at-least-once + bounded retry "for free" via AWS managed services. RabbitMQ requires opting into each one explicitly. This section consolidates the AMQP knobs the adapters must set so post-cutover failure modes match (or improve on) today's behaviour.

**(a) Publisher confirms + `mandatory`.** Channels open with `publisher_confirms=True`. `publish()` `await`s the broker's `basic.ack` for that delivery before returning. Combined with `mandatory=True` on the command publisher: a missing route returns `basic.return` and the adapter raises rather than silently drops. Together: a successful return from `publish()` / `send()` is a durable-once-returned guarantee, same as SNS.

**(b) Persistent messages.** Every publish sets `delivery_mode=DeliveryMode.PERSISTENT` (=2). Durable exchanges + durable queues only guarantee that *topology* survives broker restart; messages survive only if marked persistent. With persistent + publisher confirms + quorum queues, a message that returns from `publish()` is on disk in the quorum.

**(c) Consumer prefetch.** `await channel.set_qos(prefetch_count=max_concurrency)` (=5, matches the worker's `Semaphore(5)`). Without QoS, the broker push-streams every available message to the subscriber the moment a consumer attaches — the worker's semaphore queues them in process memory, but RabbitMQ has already accounted them as unacked. On `connect_robust` reconnect after a blip, the broker re-pushes every unacked message → mass-redelivery storm. With QoS = N, the broker only delivers up to N unacked at a time, matching SQS's per-poll `MaxNumberOfMessages` semantics.

**(d) Pull/push impedance.** `MessageConsumer.poll(max_messages, wait_seconds)` is pull-based; RabbitMQ is push-based. The adapter bridges with an internal `asyncio.Queue` buffer fed by a background pump driving `queue.iterator()`. The buffer is bounded at `prefetch_count` (=5), so QoS is what actually back-pressures the worker:

```python
class RabbitMQMessageConsumer:
    async def __aenter__(self) -> "RabbitMQMessageConsumer":
        self._channel = await self._connection.channel(publisher_confirms=False)
        await self._channel.set_qos(prefetch_count=self._prefetch)
        self._queue = await self._channel.declare_queue(
            self._queue_name,
            durable=True,
            arguments={
                "x-queue-type": "quorum",
                "x-delivery-limit": 5,
                "x-dead-letter-exchange": self._dlx,
            },
        )
        self._buffer: asyncio.Queue[Message] = asyncio.Queue(maxsize=self._prefetch)
        self._pump_task = asyncio.create_task(self._pump())
        return self

    async def _pump(self) -> None:
        async with self._queue.iterator() as it:
            async for raw in it:
                await self._buffer.put(RabbitMQMessage(raw))

    async def poll(self, max_messages: int, wait_seconds: int) -> list[Message]:
        out: list[Message] = []
        deadline = asyncio.get_event_loop().time() + wait_seconds
        while len(out) < max_messages:
            remaining = max(0.0, deadline - asyncio.get_event_loop().time())
            try:
                msg = await asyncio.wait_for(self._buffer.get(), timeout=remaining)
                out.append(msg)
            except asyncio.TimeoutError:
                break
        return out

    async def __aexit__(self, *exc: Any) -> None:
        self._pump_task.cancel()
        await asyncio.gather(self._pump_task, return_exceptions=True)
        await self._channel.close()
```

**(e) AMQP heartbeat.** `aio_pika.connect_robust(rabbitmq_url, heartbeat=30)`. aio-pika default is 60s, which means two missed heartbeats = up to 2 min to detect a dead-but-not-RST TCP connection. 30s halves that and is well below the typical 5-min connection-tracker timeout on cloud NATs.

**(f) Channel-error strategy.** `connect_robust` recovers connection-level drops automatically. It does **not** recover a channel closed by a protocol error (publish to missing exchange, ack of stale delivery tag, etc.). Strategy: **one channel per consumer + one channel per publish**. Publishers open a fresh channel inside each `publish()` / `send()` (channels are cheap on AMQP — orders of magnitude cheaper than connections) and close it on return. Consumer holds its channel for the lifetime of the `__aenter__` block; on channel-close mid-poll, the outer `worker.run()` exception-and-sleep loop (`worker.py:114-116`) catches the exception, sleeps 5s, and re-enters the consumer (which opens a new channel).

**(g) Connection lifecycle (per process, lazy, lifespan-managed).** **Honest reconciliation with the current code:** `src/listings/entrypoints/events_worker.py:71-75` constructs `SNSEventPublisher` inline in the worker entrypoint — publisher is **not** a composition-root singleton today. This spec keeps that pattern; refactoring publisher wiring into `bootstrap.py` is unrelated to the transport swap and would touch all 6 entrypoints for no transport benefit.

The change is: each `_run_*_worker()` entrypoint opens **one** `aio_pika.connect_robust(settings.rabbitmq_url, heartbeat=30)` for the worker process and passes that connection to both publisher and consumer:

```python
async def _run_events_worker() -> None:
    settings = Settings()
    connection = await aio_pika.connect_robust(settings.rabbitmq_url, heartbeat=30)
    try:
        publisher = RabbitMQEventPublisher(connection, exchange=settings.rabbitmq_domain_events_exchange)
        consumer = RabbitMQMessageConsumer(
            connection,
            queue_name="listings-events-queue",
            bindings=[("domain-events", "PROPERTY_*.v1"), ("domain-events", "PROPERTY_LISTING_*.v1")],
            prefetch_count=5,
            dlx=settings.rabbitmq_dlx,
        )
        worker = EventBusWorker(
            consumer=consumer,
            router=router,
            context=...,
            worker_name="listings_events_worker",
            use_heartbeat=False,  # RabbitMQ has no per-message visibility timeout; heartbeat would call no-op
        )
        await worker.run()
    finally:
        await connection.close()
```

For the api process: same pattern via FastAPI `lifespan` — open connection on startup, close on shutdown. The api composition root (`bootstrap.py`) is what's shared across requests, so api publisher construction *can* move into `bootstrap.py`; worker publishers stay in entrypoints.

**(h) Idempotency expectation.** RabbitMQ is at-least-once (same as SQS). After a `connect_robust` reconnect, every unacked message re-delivers immediately (vs. SQS's "wait for visibility timeout"). Reconnect storms amplify duplicate-processing potential. Handlers must be idempotent — already a property of today's code; the reconnect-storm potential makes this more load-bearing under RabbitMQ. Lock in via acceptance criteria (no code change needed today; CLAUDE.md note + ADR addendum capture the property).

### 4. Bootstrap — import swap + publisher constructor changes

`src/shared/entrypoints/bootstrap.py` currently imports `SNSEventPublisher` and `SQSCommandPublisher` (lines 56–57); `SQSMessageConsumer` is imported only in worker entrypoints, not here. After this spec, bootstrap.py imports `RabbitMQEventPublisher` and `RabbitMQCommandPublisher`; the SNS+SQS import lines are deleted. **No runtime flag, no conditional, no `event_bus_backend` setting.** The decision is made at code-write time; if we ever need to revert, we revert the import swap.

**This is more than a one-line import swap.** The 6 publisher construction sites in bootstrap.py (lines 251, 255, 457, 462, 542, 548) today look like:

```python
domain_event_publisher = SNSEventPublisher(
    session=session,
    topic_arn_prefix=settings.sns_domain_events_topic_arn_prefix,
    endpoint_url=settings.aws_endpoint_url,
)
```

After the swap each becomes:

```python
domain_event_publisher = RabbitMQEventPublisher(
    connection=amqp_connection,
    exchange=settings.rabbitmq_domain_events_exchange,
)
```

The constructor signatures differ (no `session` / `topic_arn_prefix` / `endpoint_url`; new `connection` / `exchange`). The `amqp_connection` is a new dependency — `get_*_container()` functions in bootstrap.py grow an `amqp_connection: aio_pika.RobustConnection` parameter. Callers own the connection: the api process opens it in FastAPI `lifespan` and passes it into `get_*_container()`; worker entrypoints open their own connection (covered in §3(g)) and pass it in.

Each context's `container.py` still takes the publisher / consumer at construction time, so no per-context container code change. Worker entrypoints construct their own consumer + publisher with their own bindings list.

New `Settings` fields in `src/shared/config.py`:

- `rabbitmq_url: str = ""`  (e.g. `amqp://guest:guest@localhost:5672/`)
- `rabbitmq_domain_events_exchange: str = "domain-events"`
- `rabbitmq_dlx: str = "domain-events-dlx"`

Existing `sns_domain_events_topic_arn_prefix` and `sqs_*_queue_url` fields stay in `Settings` — pydantic defaults make them harmless when unused, and the retained SNS/SQS adapter unit tests still read them. `.env.example` gains the new RabbitMQ vars; the legacy `SNS_*` / `SQS_*` entries get a brief comment marking them as "kept for the retained but unused SNS/SQS adapter classes."

### 5. Dev compose

`docker-compose.yml` at repo root — two changes so dev matches prod's transport choice:

**(a) LocalStack goes S3-only.** Change `SERVICES=sqs,sns,s3` → `SERVICES=s3`. After the import swap, no code path uses LocalStack-backed SNS or SQS, so there's no reason to keep provisioning them on startup. If `scripts/localstack-init.sh` contains SNS+SQS init steps, comment them out — keep the S3 bucket setup.

**(b) Add a `rabbitmq` service** alongside LocalStack + Redis:

```yaml
  rabbitmq:
    image: rabbitmq:3.13-management-alpine
    ports:
      - "5672:5672"    # AMQP
      - "15672:15672"  # management UI — http://localhost:15672 (guest/guest)
    environment:
      RABBITMQ_DEFAULT_USER: guest
      RABBITMQ_DEFAULT_PASS: guest
    volumes:
      - rabbitmq_data:/var/lib/rabbitmq
    healthcheck:
      test: ["CMD", "rabbitmq-diagnostics", "ping"]
      interval: 30s
```

Plus a `rabbitmq_data:` named volume at the top of the file.

After this spec ships, the dev path is:

```
RABBITMQ_URL=amqp://guest:guest@localhost:5672/
```

in `.env`, then `docker compose up -d` + `uv run uvicorn ...`. The management UI at `http://localhost:15672` (guest/guest) makes inspecting routing + bindings easy during development. **Existing devs pull, `docker compose down`, `docker compose up -d` once after this lands** — the LocalStack volume can stay (it's S3-only now); the new `rabbitmq` container provides the transport.

### 6. ADR-008 addendum + docs

- `docs/adr/008-event-bus-ports-and-fanout.md` — dated addendum (2026-05-13): RabbitMQ adapters added; `bootstrap.py` swaps imports SNS+SQS → RabbitMQ (no runtime flag). SNS+SQS adapter classes retained for unit tests + emergency revert. Port surface unchanged. Note the at-least-once + reconnect-storm property → handlers must be idempotent.
- `README.md` — dev-workflow note: `docker compose up -d` now pulls RabbitMQ as well; how to flip locally.
- `CLAUDE.md` — Worker runtime section updated: RabbitMQ is the active transport; idempotent handlers are a hard requirement.

### 7. Worker class rename + fast-quit on second signal

**Current state (captured for traceability — the rename is symbol-only, no behavior change):**

```python
# src/shared/events/worker.py (today)
"""Shared SQS-flavoured worker for the event bus.

One `SQSWorker` class. Every context — domain-event consumers AND
command-queue consumers — reuses it. ADR-006 semantics: client reuse,
batch polling, bounded concurrency, contextvars, heartbeat, drain.
..."""

class SQSWorker:
    """Port-based worker. See module docstring for failure semantics."""

    def __init__(
        self,
        consumer: MessageConsumer,
        router: EventRouter,
        context: Any,
        worker_name: str,
        use_heartbeat: bool = True,
        heartbeat_interval: int = 60,
        heartbeat_extension: int = 120,
        max_concurrency: int = 5,
        max_messages_per_poll: int = 10,
        wait_seconds: int = 20,
        drain_timeout: int = 30,
    ) -> None: ...
```

Current import sites (6 files):

- `src/properties/entrypoints/worker.py`
- `src/screening/entrypoints/worker.py`
- `src/bookings/entrypoints/events_worker.py`
- `src/contract_intelligence/entrypoints/worker.py`
- `src/organizations/entrypoints/worker.py`
- `src/listings/entrypoints/events_worker.py`

**Rename:** the class depends only on the `MessageConsumer` Protocol after the import swap — the "SQS" name is misleading. Rename to **`EventBusWorker`**. The rename ships as a **dedicated commit** (`chore(events): rename SQSWorker → EventBusWorker`) separate from any behaviour change so `git log --follow` + `git blame` stay navigable across this spec's diff.

Files touched:

- `src/shared/events/worker.py` — class name + module docstring (drop "SQS-flavoured", keep "ADR-006 semantics" + "client reuse / batch polling / bounded concurrency / contextvars / heartbeat / drain")
- All 6 import sites above — `from shared.events.worker import SQSWorker` → `EventBusWorker`

**Go-style two-strike shutdown.** The class's `_shutdown` method (line 189) currently handles SIGINT + SIGTERM by flipping `_running = False` and letting the poll loop drain. A second Ctrl+C does nothing — the handler swallows it, so an operator who's decided "actually, just kill it" has no escape hatch short of `kill -9` from another shell.

Add the Go-style two-strike pattern:

- **First signal** → existing behavior: flip `_running = False`, log a hint that another Ctrl+C will force-quit.
- **Second signal** → call `os._exit(130)` (128 + SIGINT). Brutal kill: bypasses Python's normal shutdown (no `atexit`, no buffer flush, no drain), pid dies immediately. Analogue of Go's `os.Exit`.

```python
def _shutdown(self) -> None:
    if not self._running:
        log.warning(
            f"{self._worker_name}_force_quit",
            in_flight=len(self._in_flight),
        )
        os._exit(130)
    log.info(
        f"{self._worker_name}_shutting_down",
        hint="ctrl-c again to force quit",
    )
    self._running = False
```

Intentional: if the operator hit Ctrl+C twice, they've decided the worker shouldn't bother draining. No atexit, no cleanup, no log flush — just die. Unacked messages stay unacked → broker redelivers on next consumer attach (safe by construction).

**Drain ordering with publishers.** The graceful path waits up to 30s in `_drain()` for in-flight handlers. Handlers may publish follow-up events during drain — the connection must stay open. Each worker entrypoint closes the AMQP connection in a `try/finally` **after** `worker.run()` returns, which is after drain completes. Don't close the connection inside drain.

### 8. Tests

**Unit tests per adapter** (mock `aio-pika`):

- `tests/unit/shared_events/test_rabbitmq_event_publisher.py`:
  - Publishes to configured exchange with routing-key = `event.event_type`.
  - Sets AMQP `message_id` = `event.event_id`.
  - Sets `delivery_mode=2`.
  - Opens channel with `publisher_confirms=True`; `publish` raises if broker returns `basic.nack`.
- `tests/unit/shared_events/test_rabbitmq_command_publisher.py`:
  - Publishes to default exchange with routing-key = `queue_url`.
  - `mandatory=True`; raises `DeliveryError` on `basic.return`.
- `tests/unit/shared_events/test_rabbitmq_message_consumer.py`:
  - `__aenter__` sets `basic.qos(prefetch_count=5)`.
  - Queue declared with `x-queue-type=quorum`, `x-delivery-limit=5`, `x-dead-letter-exchange=domain-events-dlx`.
  - `Message.message_id` reads AMQP property; falls back to delivery tag if absent.
  - `Message.ack` → `basic.ack`; `Message.nack` → `basic.nack(requeue=true)`.
  - `Message.extend_visibility` is a no-op (asserts no broker call).
  - Pull/push bridge: `poll()` returns up to N within `wait_seconds`, short-returns on timeout.
  - `__aexit__` cancels the pump task and closes the channel.

**Integration tests** (live broker via dev compose; skipped unless `RABBITMQ_URL` resolves):

- `tests/integration/test_rabbitmq_roundtrip.py` — publish → bound queue → consume → ack (happy path).
- `tests/integration/test_rabbitmq_persistence.py` — publish; restart the rabbitmq container; consume — message still present.
- `tests/integration/test_rabbitmq_retry_budget.py` — handler always raises → message lands in `dead-letters` queue after **exactly** 5 attempts; assert `x-death` header count.
- `tests/integration/test_rabbitmq_reconnect.py` — kill the rabbitmq container mid-poll; restart; verify worker reconnects (via `connect_robust`) and resumes without message loss.
- `tests/integration/test_rabbitmq_mandatory.py` — `send()` to a non-existent queue name raises `DeliveryError`.
- `tests/integration/test_rabbitmq_prefetch.py` — pre-load 100 messages on a queue; verify consumer never holds more than `prefetch_count` unacked at any point.

## Affected files / surfaces

**New:**
- `src/shared/events/adapters/rabbitmq_event_publisher.py`
- `src/shared/events/adapters/rabbitmq_command_publisher.py`
- `src/shared/events/adapters/rabbitmq_message_consumer.py`
- `tests/unit/shared_events/test_rabbitmq_event_publisher.py`
- `tests/unit/shared_events/test_rabbitmq_command_publisher.py`
- `tests/unit/shared_events/test_rabbitmq_message_consumer.py`
- `tests/integration/test_rabbitmq_roundtrip.py`
- `tests/integration/test_rabbitmq_persistence.py`
- `tests/integration/test_rabbitmq_retry_budget.py`
- `tests/integration/test_rabbitmq_reconnect.py`
- `tests/integration/test_rabbitmq_mandatory.py`
- `tests/integration/test_rabbitmq_prefetch.py`

**Modified:**
- `docker-compose.yml` (dev) — add `rabbitmq` service + named volume; LocalStack `SERVICES=s3`
- `src/shared/entrypoints/bootstrap.py` — swap SNS+SQS imports for RabbitMQ; api-side singleton connection via FastAPI `lifespan`
- `src/shared/events/worker.py` — rename `SQSWorker` → `EventBusWorker` + double-Ctrl+C fast-quit (`os._exit(130)`)
- `src/properties/entrypoints/worker.py`, `src/screening/entrypoints/worker.py`, `src/bookings/entrypoints/events_worker.py`, `src/contract_intelligence/entrypoints/worker.py`, `src/organizations/entrypoints/worker.py`, `src/listings/entrypoints/events_worker.py` — update import + instantiation to `EventBusWorker`; open one `connect_robust` per process; close in outer `try/finally` after `worker.run()` returns
- `src/shared/config.py` — add three new RabbitMQ fields (no `event_bus_backend` flag)
- `.env.example` — add `RABBITMQ_*` vars; mark `SNS_*` / `SQS_*` as legacy
- `pyproject.toml` + `uv.lock` — add `aio-pika`
- `docs/adr/008-event-bus-ports-and-fanout.md` — addendum
- `README.md` — dev-workflow notes; idempotency requirement
- `CLAUDE.md` — Worker runtime section
- `scripts/localstack-init.sh` (if it contains SNS/SQS init) — comment those steps out

**Read-only sources of truth:**
- `src/shared/events/ports.py` — the four Protocol ports
- `src/shared/events/adapters/sns_event_publisher.py`, `sqs_command_publisher.py`, `sqs_message_consumer.py` — reference shapes

**Explicitly untouched:**
- `src/shared/events/adapters/sns_*.py`, `sqs_*.py`, `inmemory_event_bus.py`
- `src/shared/events/lambda_handler.py`, `lambda_bootstrap.py`
- All Lambda entrypoints + `terraform/production/**`
- `deploy/docker-compose.prod.yml` (owned by `2026-05-coolify-compose-prod`)
- Every context's `container.py`

## Acceptance criteria

### Ports + adapters
- [ ] The four Protocols in `src/shared/events/ports.py` are unchanged.

### Publishers
- [ ] `RabbitMQEventPublisher.publish(event)` publishes to `${rabbitmq_domain_events_exchange}` with routing-key = `event.event_type`, body = `event.to_json()`, AMQP `message_id` = `event.event_id`, `delivery_mode=2`.
- [ ] `RabbitMQCommandPublisher.send(queue_url, event)` publishes to the default exchange with routing-key = `queue_url`, AMQP `message_id` = `event.event_id`, `delivery_mode=2`, `mandatory=True`. Misroute raises `DeliveryError` (no silent drop).
- [ ] Both publishers operate on channels opened with `publisher_confirms=True`; `publish/send` returns only after broker `basic.ack`. Broker `basic.nack` raises.
- [ ] Publishers open a **new channel per publish** (cheap on AMQP) and close on return — isolates channel-level errors per publish.

### Consumer
- [ ] `RabbitMQMessageConsumer.__aenter__` opens a channel, sets `basic.qos(prefetch_count=max_concurrency)`, declares the queue idempotently with `x-queue-type=quorum`, `x-delivery-limit=5`, `x-dead-letter-exchange=domain-events-dlx`, and binds it to `domain-events` for each routing-key pattern passed in.
- [ ] `poll(max_messages, wait_seconds)` returns up to `max_messages` messages within `wait_seconds`, sourced from an internal `asyncio.Queue` buffer bounded at `prefetch_count` and fed by a background task driving `queue.iterator()`.
- [ ] `__aexit__` cancels the pump task and closes the channel; pump-task exceptions don't propagate.

### Messages
- [ ] `RabbitMQMessage.message_id` returns the AMQP `message_id` property; falls back to delivery tag only if absent.
- [ ] `RabbitMQMessage.ack` → `basic.ack`.
- [ ] `RabbitMQMessage.nack` → `basic.nack(requeue=true)`. Verified: after 5 redeliveries on the same message, broker routes to `dead-letters` queue (matches SQS `maxReceiveCount=5`); `x-death` header shows count=5.
- [ ] `RabbitMQMessage.extend_visibility` is a no-op; docstring explicitly says so.

### Connection lifecycle
- [ ] Each worker entrypoint opens **one** `aio_pika.connect_robust(rabbitmq_url, heartbeat=30)` for the process and passes that connection to both publisher and consumer.
- [ ] After `worker.run()` returns (i.e. after drain completes), the entrypoint closes the connection in a `try/finally`. Connection outlives drain.
- [ ] api process opens its connection in `bootstrap.py` via FastAPI `lifespan`; closes on shutdown.
- [ ] `connect_robust` is called with `heartbeat=30` everywhere.

### Bootstrap
- [ ] `bootstrap.py` imports `RabbitMQEventPublisher` / `RabbitMQCommandPublisher` / `RabbitMQMessageConsumer` directly. Previous `SNSEventPublisher` / `SQSCommandPublisher` / `SQSMessageConsumer` import lines are deleted. No runtime flag, no conditional, no `event_bus_backend` setting.
- [ ] No context's `container.py` is modified.

### Compose / config
- [ ] `docker-compose.yml` (dev) has a `rabbitmq` service exposing 5672 + 15672 with a persistent `rabbitmq_data` volume. LocalStack `SERVICES` env value is `s3` (no `sqs`, no `sns`).
- [ ] `.env.example` documents `RABBITMQ_URL`, `RABBITMQ_DOMAIN_EVENTS_EXCHANGE`, `RABBITMQ_DLX`. Legacy `SNS_*` / `SQS_*` entries get a comment marking them as kept-for-retained-adapter-unit-tests.
- [ ] `aio-pika` is added to `pyproject.toml` and `uv.lock`.

### Worker class
- [ ] `SQSWorker` class renamed to `EventBusWorker`. No file imports `SQSWorker` after this spec; module docstring updated; every context's worker entrypoint imports `EventBusWorker`.
- [ ] The rename is a dedicated commit (`chore(events): rename SQSWorker → EventBusWorker`) separate from the fast-quit behavior change and the RabbitMQ adapter work, so `git blame` doesn't conflate them.
- [ ] `EventBusWorker._shutdown` is upgraded: first SIGINT/SIGTERM flips `_running = False` and logs a "ctrl-c again to force quit" hint; second signal calls `os._exit(130)` to brutally kill the process without drain or atexit hooks.
- [ ] All worker entrypoints construct `EventBusWorker` with `use_heartbeat=False` — RabbitMQ has no per-message visibility timeout, so the heartbeat task would burn cycles calling no-op `extend_visibility` every 60s. (The `_heartbeat` helper stays in `worker.py` for SNS+SQS adapter unit tests.)

### Idempotency
- [ ] CLAUDE.md "Worker runtime" + ADR-008 addendum explicitly call out: handlers must be idempotent. RabbitMQ reconnect can cause immediate redelivery of all unacked messages (unlike SQS, which waits for visibility timeout). No handler code is modified in this spec; this is a property the existing handlers already have, locked in.

### Tests
- [ ] Unit tests cover publish-with-confirms, `mandatory` misroute raising, `delivery_mode=2`, prefetch QoS setting, queue-declare args, message_id wrapping, pull/push buffer semantics.
- [ ] Integration tests cover: round-trip, broker-restart persistence, retry-budget → DLX (count=5), connection-drop reconnect with no message loss, mandatory misroute raising, prefetch cap not exceeded under load. Gated on `RABBITMQ_URL` resolving.

### Preservation
- [ ] No file under `src/shared/events/adapters/sns_*.py`, `sqs_*.py`, `inmemory_event_bus.py`, `terraform/production/**`, `src/**/lambda_*.py`, or `deploy/docker-compose.prod.yml` is modified.
- [ ] `docs/adr/008-event-bus-ports-and-fanout.md` has a dated addendum.
- [ ] README documents the new dev workflow.

## Open questions

- **Exchange topology for fan-out:** single topic exchange with per-event routing keys vs. per-event-type exchanges. **Default: single topic exchange.** Switch only if a concrete subscription-management need surfaces.
- **DLX strategy:** single global `domain-events-dlx` vs. per-queue DLX. **Default: single global DLX** with `x-death` headers identifying origin.
- **Queue declarations:** on consumer `__aenter__` (idempotent) vs. via a one-shot init container. **Default: consumer-side**, fewer moving parts.
- **`consumer_timeout` headroom:** broker default (30 min) caps unacked handler runtime. The 15-min enrichment claim came from the Lambda spec — verify against the real enrichment p99 once RabbitMQ is exercised on dev. If any handler exceeds ~25 min in practice, bump `consumer_timeout` via `rabbitmq.conf` or `rabbitmqctl set_parameter`. Out-of-scope to wire automation here.
- **Reconnect-storm pressure on Supabase / external APIs:** after a broker blip, every unacked message redelivers at once. If a worker had 5 in-flight handlers calling OpenAI when the broker dropped, those 5 retries all hit OpenAI simultaneously. Probably fine at our volume — flag for ops awareness, capture if it ever bites.

## Out of scope follow-ups

- Flipping prod compose to use RabbitMQ (handled by `2026-05-coolify-compose-prod`).
- Decommissioning SNS topics + SQS queues + Lambda event source mappings after Coolify runs cleanly on RabbitMQ.
- `init-broker` service that pre-declares exchanges + queues + bindings on first deploy.
- Per-queue DLX (currently single global DLX).
- Refactoring publisher construction into `bootstrap.py` for worker entrypoints (matches the api pattern; currently each worker entrypoint constructs its own publisher).
- Chaos tooling for ongoing reliability verification (broker kill, network partition, etc.) beyond the initial integration test suite.

## Commits

- `chore(events): rename SQSWorker → EventBusWorker (symbol-only)` — captures the pre-rename state so the next commits don't muddle blame.
- `feat(events): EventBusWorker fast-quit on second SIGINT (os._exit)` — Go-style two-strike shutdown.
- `feat(events): RabbitMQ adapters with publisher-confirms + persistent + qos + dlx (aio-pika)` — three new adapters; existing SNS+SQS untouched.
- `feat(events): swap bootstrap imports SNS+SQS → RabbitMQ` — single-line cutover; no runtime flag.
- `feat(events): per-process connect_robust + heartbeat=30 in worker entrypoints` — 6 entrypoints touched.
- `feat(deploy): rabbitmq service in dev docker-compose; LocalStack to S3-only` — dev path matches prod's transport.
- `test(events): integration tests for persistence, retry budget, reconnect, mandatory, prefetch`
- `docs(adr): ADR-008 addendum — RabbitMQ adapters as the active transport; idempotency locked in`
