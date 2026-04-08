# ADR-006: SQS worker reliability and observability improvements

**Date:** 2026-03-31
**Status:** Proposed

## Context

We have two SQS worker implementations across bounded contexts. The contract_intelligence worker is more mature, but both share fundamental issues that affect reliability and observability in production.

### Current state

| Capability | contract_intelligence | screening |
|---|---|---|
| Per-message error handling | Yes | No |
| Visibility timeout heartbeat | Yes | No |
| Processing duration logging | Yes | No |
| DLQ support | Yes (dedicated worker) | No |
| SQS client reuse | No (new client per call) | No (new client per call) |
| Concurrent processing | No (1 msg at a time) | No (1 msg at a time) |
| Structured message context in logs | No | No |
| Graceful shutdown (drain in-flight) | No (flag only) | No (flag only) |
| Metrics emission | No | No |

### Problems

**1. SQS client churn** — Every `_poll()` and `_delete_message()` call creates a new SQS client via `async with session.client("sqs")`. Each creation involves TLS negotiation and credential resolution. At 3 calls/message (poll + process + delete), this adds ~100-300ms of overhead per message for no reason.

```python
# Current: new client per operation
async def _poll(self):
    async with self._session.client("sqs", **kwargs) as sqs:  # new client
        response = await sqs.receive_message(...)

async def _delete_message(self, receipt_handle):
    async with self._session.client("sqs", **kwargs) as sqs:  # another new client
        await sqs.delete_message(...)
```

**2. Sequential single-message processing** — `MaxNumberOfMessages=1` means we make one SQS API call per message, each with a 20s long-poll. Worst case: 3 msg/min throughput even if processing takes <1s. SQS allows up to 10 messages per `ReceiveMessage` call.

**3. No structured context per message** — When a message fails, the error log has no `document_id`, `event_type`, or `message_id`. Debugging requires correlating timestamps across logs manually.

**4. No drain on shutdown** — `_shutdown()` sets `_running = False`, but if concurrent processing is added later, in-flight tasks would be abandoned. The worker should wait for in-flight work to complete (with a timeout) before exiting.

**5. No metrics** — No processing latency histograms, no error counters, no queue depth gauges. We can't alert on degradation or track SLA compliance.

## Decision

Improve the contract_intelligence `SQSWorker` as the reference implementation, then replicate to screening. Changes are additive — no architectural changes to the worker pattern itself.

### 1. Reuse SQS client across the worker lifecycle

Create the client once in `run()` and pass it to `_poll()` and `_delete_message()`:

```python
async def run(self) -> None:
    log.info(f"{self._worker_name}_started", queue_url=self._queue_url)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, self._shutdown)

    kwargs: dict[str, Any] = {}
    if self._endpoint_url:
        kwargs["endpoint_url"] = self._endpoint_url

    async with self._session.client("sqs", **kwargs) as sqs:
        self._sqs = sqs
        while self._running:
            try:
                messages = await self._poll()
                for msg in messages:
                    await self._process_message(msg)
            except Exception:
                log.exception(f"{self._worker_name}_error")
                await asyncio.sleep(5)
```

### 2. Batch polling with concurrent processing

Increase `MaxNumberOfMessages` to 10 and process with a semaphore-bounded task group:

```python
class SQSWorker:
    def __init__(self, ..., max_concurrency: int = 5) -> None:
        ...
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def run(self) -> None:
        ...
        async with self._session.client("sqs", **kwargs) as sqs:
            self._sqs = sqs
            while self._running:
                try:
                    messages = await self._poll()
                    tasks = [self._bounded_process(msg) for msg in messages]
                    await asyncio.gather(*tasks, return_exceptions=True)
                except Exception:
                    log.exception(f"{self._worker_name}_error")
                    await asyncio.sleep(5)

    async def _bounded_process(self, msg: dict[str, Any]) -> None:
        async with self._semaphore:
            await self._process_message(msg)

    async def _poll(self) -> list[dict[str, Any]]:
        response = await self._sqs.receive_message(
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=20,
        )
        ...
```

### 3. Structured per-message logging with contextvars

Bind message context at the start of processing so all downstream logs include it:

```python
import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

async def _process_message(self, msg: dict[str, Any]) -> None:
    clear_contextvars()
    bind_contextvars(
        worker=self._worker_name,
        document_id=msg["body"].get("document_id"),
        event_type=msg["body"].get("event_type"),
    )
    start = time.monotonic()
    ...
    elapsed = time.monotonic() - start
    log.info("message_processed", processing_seconds=round(elapsed, 2))
```

### 4. Graceful shutdown with in-flight drain

Wait for in-flight tasks to complete before exiting:

```python
def _shutdown(self) -> None:
    log.info(f"{self._worker_name}_shutting_down")
    self._running = False

async def run(self) -> None:
    ...
    async with self._session.client("sqs", **kwargs) as sqs:
        self._sqs = sqs
        while self._running:
            try:
                messages = await self._poll()
                self._in_flight = [
                    asyncio.create_task(self._bounded_process(msg))
                    for msg in messages
                ]
                await asyncio.gather(*self._in_flight, return_exceptions=True)
                self._in_flight = []
            except Exception:
                log.exception(f"{self._worker_name}_error")
                await asyncio.sleep(5)

        # Drain: wait for any in-flight tasks on shutdown
        if self._in_flight:
            log.info(f"{self._worker_name}_draining", count=len(self._in_flight))
            done, pending = await asyncio.wait(self._in_flight, timeout=30)
            for task in pending:
                task.cancel()
            log.info(f"{self._worker_name}_drain_complete",
                     completed=len(done), cancelled=len(pending))
```

### 5. Metrics via structlog (no vendor coupling)

Emit key metrics as structured log events. These are picked up by log-based metric systems (CloudWatch Logs Insights, Datadog log-to-metrics, Grafana Loki):

```python
# On every message
log.info("message_processed",
    processing_seconds=round(elapsed, 2),
    worker=self._worker_name,
    status="success",  # or "error"
)

# On error
log.error("message_failed",
    worker=self._worker_name,
    error_type=type(exc).__name__,
)

# Periodically (every N polls)
log.info("worker_health",
    worker=self._worker_name,
    active_tasks=self._semaphore._value,  # available permits
    poll_count=self._poll_count,
)
```

No OpenTelemetry SDK required at this stage. When we need trace correlation or histogram metrics, we add OTel as a structlog processor — no worker code changes needed.

### Screening-specific additions

Port from contract_intelligence:
- **Heartbeat** — screening's extraction processor calls Reducto (can take 30-60s). Without heartbeat, messages with default 30s visibility timeout will be redelivered mid-processing.
- **Per-message try/except** — wrap each message processing, log the error with context, and still delete the message (failed documents stay in their current status and can be re-queued).
- **DLQ** — configure redrive policy on both screening queues. Add a DLQ processor that marks documents/applicants as failed.

## Implementation order

1. **Client reuse** — smallest change, biggest efficiency win
2. **Structured logging + duration** — immediate observability gain
3. **Port heartbeat + per-message error handling to screening** — reliability parity
4. **Batch polling + semaphore concurrency** — throughput improvement
5. **Graceful drain** — operational safety
6. **DLQ for screening** — failure handling parity

Steps 1-3 can ship independently. Steps 4-5 ship together (concurrency requires drain). Step 6 requires SQS queue infrastructure changes (redrive policy).

## Consequences

### Positive

- **Client reuse** eliminates ~100-300ms overhead per message
- **Batch + concurrency** increases theoretical throughput from ~3 msg/min to ~30 msg/min per pod
- **Structured logs** make debugging production issues possible without log timestamp correlation
- **Graceful drain** prevents message loss during deployments (k8s sends SIGTERM, waits `terminationGracePeriodSeconds`, then SIGKILL)
- **Screening parity** — both contexts share the same reliability baseline

### Negative

- **Concurrent processing adds complexity** — semaphore bounds, task tracking, drain logic
- **Batch delete would be more efficient** but adds complexity (collecting receipt handles, partial failure handling) — defer to a future iteration

### Risks

- **Concurrent DB access** — multiple messages processed simultaneously share the same container but each gets its own UoW session (per ADR-005), so this is safe
- **Concurrent AI API calls** — Reducto and LLM providers have rate limits. The semaphore (`max_concurrency=5`) should be tuned to stay under rate limits. Start conservative.
