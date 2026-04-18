# TLDR: SQS Worker Code Walkthrough

> **⚠️ Superseded by [ADR-008](../adr/008-event-bus-ports-and-fanout.md).** The per-context `SQSWorker` class walked through here has been deleted and replaced by `src/shared/events/worker.py:SQSWorker` — one class, used by every context, taking a `MessageConsumer` port + `EventRouter` instead of a raw `aioboto3.Session` + processor module. Handler signatures also changed from `process_event(body, container)` to `(event: DomainEvent, context) -> None`. Kept for historical context.

A line-by-line explanation of the (now-deleted) pre-ADR-008 `SQSWorker` class from `src/contract_intelligence/entrypoints/worker.py` after the ADR-006 changes. The screening worker was structurally identical.

## Imports

```python
import argparse
import asyncio
import json
import signal
import time
from typing import Any

import aioboto3
import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars
```

- **`asyncio`** — the event loop, tasks, semaphores, and `gather`/`wait` primitives.
- **`signal`** — Unix signals (SIGTERM from k8s, SIGINT from Ctrl+C).
- **`time`** — `time.monotonic()` for measuring processing duration. Monotonic clock can't go backwards on NTP adjustments, so it's safer than `time.time()` for elapsed measurements.
- **`aioboto3`** — async wrapper around `botocore`. Provides `Session.client("sqs")` as an async context manager.
- **`structlog.contextvars`** — `bind_contextvars` attaches key-value pairs to the current asyncio task context. Any subsequent `log.info()` call from inside that context (including from deeper code like services and repositories) automatically includes those keys, without threading them through function signatures.

## The heartbeat function

```python
async def _heartbeat(
    sqs: Any,
    queue_url: str,
    receipt_handle: str,
    interval: int = 60,
    extension: int = 120,
) -> None:
```

A standalone coroutine that runs in the background while a single message is being processed. It periodically extends the SQS visibility timeout so that long-running tasks don't get the message redelivered to another consumer.

- **`sqs`** — the shared SQS client, passed in instead of creating a new one. This is a key change from the previous version: heartbeats are no longer responsible for opening their own connection.
- **`receipt_handle`** — the unique token returned by `ReceiveMessage`. Required to identify which in-flight message to extend.
- **`interval=60, extension=120`** — every 60 seconds, push the visibility timeout out by 120 seconds. The 2x ratio gives a one-tick safety buffer: if a heartbeat fails, the next one still has time to recover before the message becomes visible again.

```python
    extensions = 0
    try:
        while True:
            await asyncio.sleep(interval)
            try:
                await sqs.change_message_visibility(
                    QueueUrl=queue_url,
                    ReceiptHandle=receipt_handle,
                    VisibilityTimeout=extension,
                )
                extensions += 1
                log.debug("heartbeat_extended", queue_url=queue_url, extensions=extensions)
            except Exception:
                log.warning(
                    "heartbeat_extension_failed", queue_url=queue_url, extensions=extensions
                )
    except asyncio.CancelledError:
        log.debug("heartbeat_stopped", queue_url=queue_url, total_extensions=extensions)
```

- The outer `try/except CancelledError` catches the cancellation that happens when the message finishes processing. `_process_message` calls `heartbeat_task.cancel()` in its `finally` block; that raises `CancelledError` inside the heartbeat at the next `await`. We catch it just to log cleanly.
- The inner `try/except Exception` ensures a transient SQS error doesn't kill the heartbeat — we log a warning and try again on the next tick. A failing heartbeat is not a reason to abandon the message; the worst case is the visibility timeout expires and SQS redelivers, at which point the redelivery handler runs the same processor.
- **`extensions`** counter is logged on every tick and on cancellation, useful for spotting messages that take unusually long.

## The SQSWorker class — `__init__`

```python
class SQSWorker:
    def __init__(
        self,
        session: aioboto3.Session,
        queue_url: str,
        container: Any,
        processor: Any,
        endpoint_url: str | None = None,
        worker_name: str = "sqs_worker",
        use_heartbeat: bool = False,
        heartbeat_interval: int = 60,
        heartbeat_extension: int = 120,
        max_concurrency: int = 5,
        max_messages_per_poll: int = 10,
        drain_timeout: int = 30,
    ) -> None:
```

The worker is parameterized so the same class powers all three queues (ingestion, analysis, DLQ).

- **`session`** — `aioboto3.Session`, not the client. The client is opened later inside `run()`. Sessions are cheap; clients hold connections.
- **`container`** — the bounded context's DI container (with services, UoW, etc.). Passed through unchanged to the processor.
- **`processor`** — a module with `async def process_event(body, container)`. Indirection via this argument is what lets one `SQSWorker` class serve all three queue types.
- **`endpoint_url`** — only set in local dev (LocalStack). In production it's `None` and aioboto3 hits the real AWS endpoint.
- **`use_heartbeat`** — turn the heartbeat on for queues whose processors do long external I/O (Reducto OCR, LLM calls). The DLQ worker leaves it off — DLQ processing is just a status update.
- **`max_concurrency=5`** — how many messages this worker processes at the same time. This is the **semaphore size**, not the thread count. All concurrent tasks run on the same event loop.
- **`max_messages_per_poll=10`** — SQS allows up to 10 per `ReceiveMessage`. Polling 10-at-a-time amortizes the 20s long-poll wait across more work.
- **`drain_timeout=30`** — on shutdown, how long to wait for in-flight messages before forcefully cancelling them. Should be slightly less than the k8s `terminationGracePeriodSeconds` so we drain before SIGKILL.

```python
        self._session = session
        self._queue_url = queue_url
        self._container = container
        self._processor = processor
        self._endpoint_url = endpoint_url
        self._worker_name = worker_name
        self._use_heartbeat = use_heartbeat
        self._heartbeat_interval = heartbeat_interval
        self._heartbeat_extension = heartbeat_extension
        self._max_concurrency = max_concurrency
        self._max_messages_per_poll = max_messages_per_poll
        self._drain_timeout = drain_timeout
        self._running = True
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._in_flight: list[asyncio.Task] = []
        self._sqs: Any = None
```

- **`self._running = True`** — the loop's exit flag. The signal handler flips this to `False`.
- **`self._semaphore = asyncio.Semaphore(max_concurrency)`** — the bounded-concurrency primitive. Each `_bounded_process` call must `acquire()` a permit before processing and `release()` after. With 5 permits and 10 messages from a poll, only 5 are processed at once; the other 5 await on `acquire()` until a permit frees up.
- **`self._in_flight: list[asyncio.Task]`** — the live task handles for messages currently being processed. Used by `_drain()` on shutdown.
- **`self._sqs`** — placeholder for the shared SQS client. Filled in by `run()`.

## `run()` — the main loop

```python
    async def run(self) -> None:
        log.info(
            f"{self._worker_name}_started",
            queue_url=self._queue_url,
            max_concurrency=self._max_concurrency,
            max_messages_per_poll=self._max_messages_per_poll,
        )
```

A startup log line that includes the tunable parameters. Useful when debugging — you can verify a deployed pod was actually configured the way you expected.

```python
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._shutdown)
```

Registers `_shutdown` as the handler for both signals. `add_signal_handler` (vs the standard `signal.signal()`) is asyncio-aware: when the signal arrives, the loop schedules `_shutdown()` as a callback rather than interrupting whatever coroutine is running. This guarantees we don't crash mid-`await`.

- **SIGTERM** — what k8s sends when terminating a pod (rolling deploy, scale-down).
- **SIGINT** — what Ctrl+C sends in dev.

```python
        kwargs: dict[str, Any] = {}
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url
```

Builds the kwargs for `session.client("sqs")`. Only set `endpoint_url` when running against LocalStack — in production we leave it unset so botocore picks the real AWS endpoint based on region.

```python
        async with self._session.client("sqs", **kwargs) as sqs:
            self._sqs = sqs
```

**The single most impactful change.** One SQS client created here, used for the entire worker's lifetime. Behind the scenes, `aiobotocore` opens an `aiohttp.ClientSession` with a connection pool. Subsequent `receive_message`, `delete_message`, and `change_message_visibility` calls reuse the existing TLS connection.

This is safe even though multiple coroutines call the client concurrently: asyncio is cooperative (only one coroutine runs at a time), and `aiohttp`'s pool hands out idle connections to whichever coroutine asks. There are no locks needed and no race conditions, because nothing executes Python code in parallel within a single event loop.

```python
            while self._running:
                try:
                    messages = await self._poll()
                    if not messages:
                        continue
```

Long-poll for messages. If SQS returns nothing (the queue is empty), `_poll` returns an empty list and we loop back to poll again. The 20s `WaitTimeSeconds` inside `_poll` means each empty cycle takes 20s, not a busy-wait.

```python
                    self._in_flight = [
                        asyncio.create_task(self._bounded_process(msg)) for msg in messages
                    ]
                    await asyncio.gather(*self._in_flight, return_exceptions=True)
                    self._in_flight = []
```

The concurrency core:

1. **`asyncio.create_task(...)`** — schedules each `_bounded_process(msg)` as an independent task on the event loop. All N tasks start "running" immediately, but only `max_concurrency` of them get past the semaphore acquire.
2. **`self._in_flight = [...]`** — we keep references both for `gather()` and for `_drain()` to find on shutdown.
3. **`asyncio.gather(*tasks, return_exceptions=True)`** — waits for all tasks to finish. `return_exceptions=True` means a single failing message doesn't propagate an exception out of `gather` and break the outer try/except. Per-message errors are already caught inside `_process_message`.
4. **`self._in_flight = []`** — cleared once the batch is done so the drain logic on shutdown doesn't see stale tasks.

```python
                except Exception:
                    log.exception(f"{self._worker_name}_error")
                    await asyncio.sleep(5)
```

Outer safety net for poll-level failures (e.g., SQS API throwing on a malformed receipt handle, JSON decode errors). We log with traceback, sleep 5s to avoid hot-looping on a persistent failure, then continue.

```python
            await self._drain()
```

When the `while self._running` loop exits (because `_shutdown` flipped the flag), call `_drain()` to wait for any remaining in-flight tasks before the `async with` closes the SQS client.

## `_drain()` — graceful shutdown

```python
    async def _drain(self) -> None:
        if not self._in_flight:
            return
        log.info(f"{self._worker_name}_draining", in_flight=len(self._in_flight))
        done, pending = await asyncio.wait(self._in_flight, timeout=self._drain_timeout)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        log.info(
            f"{self._worker_name}_drain_complete",
            completed=len(done),
            cancelled=len(pending),
        )
```

- **`asyncio.wait(..., timeout=30)`** — waits for all in-flight tasks, but returns after 30s regardless. Returns two sets: `done` (finished) and `pending` (still running).
- **`task.cancel()`** — for stragglers, schedule cancellation. This raises `CancelledError` inside the task at its next `await`.
- **`await asyncio.gather(*pending, return_exceptions=True)`** — wait for the cancellations to actually take effect. Without this `await`, the function would return before cancelled tasks finish their cleanup, and the SQS client would close while they're still trying to use it.

The signal flow on Ctrl+C / SIGTERM is now:
1. Signal arrives → `_shutdown()` runs as a loop callback → sets `_running = False`.
2. Current poll/process cycle finishes its `gather()`.
3. `while self._running` evaluates `False`, loop exits.
4. `_drain()` waits up to 30s for in-flight messages.
5. `async with` closes the SQS client cleanly.

## `_bounded_process()` — the semaphore gate

```python
    async def _bounded_process(self, msg: dict[str, Any]) -> None:
        async with self._semaphore:
            await self._process_message(msg)
```

Three-line function but conceptually load-bearing. `async with self._semaphore` acquires a permit on entry and releases on exit (even on exception). Only `max_concurrency` coroutines can be inside `_process_message` at any moment. The rest sit at the `async with` line, suspended, waiting for a permit.

This is what gives us **backpressure**: if all 5 permits are held by long-running messages, the other 5 from the batch wait — they don't drown the downstream services with parallel API calls.

## `_process_message()` — the per-message lifecycle

```python
    async def _process_message(self, msg: dict[str, Any]) -> None:
        clear_contextvars()
        body = msg["body"] if isinstance(msg["body"], dict) else {}
        bind_contextvars(
            worker=self._worker_name,
            message_id=msg.get("message_id"),
            document_id=body.get("document_id"),
            event_type=body.get("event_type"),
        )
```

- **`clear_contextvars()`** — start with a clean context. This is critical when the same task slot is reused for many messages: without clearing, leftover keys from a previous message would leak into the new message's logs.
- **`bind_contextvars(...)`** — attach the message metadata to the current task's logging context. From this point on, every `log.info("foo")` from any code reached by this coroutine — including services, repositories, downstream API client wrappers — will automatically include `worker`, `message_id`, `document_id`, and `event_type` in the structured output. This is the single biggest debugging win in the rewrite.

```python
        heartbeat_task: asyncio.Task | None = None
        start = time.monotonic()
```

- **`start = time.monotonic()`** — capture the start time for duration measurement. Monotonic clock can't be affected by NTP adjustments, so the elapsed value is always correct.

```python
        if self._use_heartbeat:
            heartbeat_task = asyncio.create_task(
                _heartbeat(
                    self._sqs,
                    self._queue_url,
                    msg["receipt_handle"],
                    interval=self._heartbeat_interval,
                    extension=self._heartbeat_extension,
                )
            )
```

If heartbeats are enabled, fire one off as a background task **before** starting the actual processor. The heartbeat task runs concurrently with `process_event` on the same event loop. We hold the task handle so we can cancel it in `finally`.

```python
        try:
            await self._processor.process_event(msg["body"], self._container)
            elapsed = time.monotonic() - start
            log.info(
                f"{self._worker_name}_message_processed",
                processing_seconds=round(elapsed, 2),
                status="success",
            )
```

The actual work. `process_event` is the queue-specific function (ingestion, analysis, screening, etc.) that calls into the application services via the container. On success, we log with `processing_seconds` and `status="success"` — both fields are designed to be picked up by log-based metrics systems (CloudWatch Logs Insights, Datadog log-to-metrics, Grafana Loki).

```python
        except Exception as exc:
            elapsed = time.monotonic() - start
            log.exception(
                f"{self._worker_name}_message_error",
                processing_seconds=round(elapsed, 2),
                status="error",
                error_type=type(exc).__name__,
                raw_body=msg.get("body"),
            )
```

- **`log.exception`** (vs `log.error`) — automatically includes the traceback in the log record.
- **`error_type=type(exc).__name__`** — the exception class name as a separate field. This makes it easy to count error types in dashboards (`error_type:DocumentNotFoundError` vs `error_type:OpenAITimeoutError`) without parsing the message string.
- **`raw_body`** — the full original payload, in case the error was caused by a malformed event.
- We do **not** re-raise. The processor's exception is fully handled here so the outer `gather` doesn't see it. Failed messages are still deleted (see `finally` below) — we rely on the application services to mark domain entities as FAILED so failures are visible in the database, not just in logs.

```python
        finally:
            try:
                await self._delete_message(msg["receipt_handle"])
            except Exception:
                log.exception(f"{self._worker_name}_delete_failed")
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)
            clear_contextvars()
```

The cleanup block, runs on both success and failure:

1. **`_delete_message`** — always delete the message from SQS, even on failure. Wrapped in its own try/except because a delete failure mid-cleanup must not prevent the heartbeat cancellation. If the delete fails, the message will be redelivered later, and our processors are designed to be idempotent (the application services check current entity state before mutating).
2. **`heartbeat_task.cancel()`** — schedules cancellation of the background heartbeat. The next `await` inside the heartbeat raises `CancelledError`, which the heartbeat catches to log and exit cleanly.
3. **`await asyncio.gather(heartbeat_task, ...)`** — wait for the cancellation to complete. Without this `await`, the heartbeat could still be mid-`change_message_visibility` when the SQS client closes, leading to "client closed" errors in logs.
4. **`clear_contextvars()`** — wipe the message context so the next message doesn't inherit stale fields.

## `_poll()`

```python
    async def _poll(self) -> list[dict[str, Any]]:
        response = await self._sqs.receive_message(
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=self._max_messages_per_poll,
            WaitTimeSeconds=20,
        )
```

- **`MaxNumberOfMessages=10`** (the configured default) — request up to 10 messages per call. SQS may return fewer; that's fine.
- **`WaitTimeSeconds=20`** — long polling. The call blocks on the SQS side for up to 20 seconds waiting for messages to appear, instead of returning immediately with an empty response. This dramatically reduces the number of API calls (and cost) on idle queues.
- Note this method is now trivially short — it just calls `self._sqs.receive_message`. No more `async with session.client("sqs")` overhead per call.

```python
        messages = response.get("Messages", [])
        return [
            {
                "body": json.loads(msg["Body"]),
                "receipt_handle": msg["ReceiptHandle"],
                "message_id": msg.get("MessageId"),
            }
            for msg in messages
        ]
```

Normalize the SQS response into a simpler shape:
- **`body`** — parsed JSON. The SQS body is always a string.
- **`receipt_handle`** — needed for `delete_message` and `change_message_visibility`.
- **`message_id`** — included for logging context (not for any SQS operation; it's just an identifier).

## `_delete_message()`

```python
    async def _delete_message(self, receipt_handle: str) -> None:
        await self._sqs.delete_message(QueueUrl=self._queue_url, ReceiptHandle=receipt_handle)
```

Now a one-liner. Compare to the previous version which opened a fresh client on every call. This is the second half of the client-reuse win.

## `_shutdown()`

```python
    def _shutdown(self) -> None:
        log.info(f"{self._worker_name}_shutting_down")
        self._running = False
```

Synchronous (not `async`) — required by `loop.add_signal_handler`, which calls it as a normal callback. All it does is flip the flag and log. The actual cleanup happens in `run()` after the next loop iteration sees `_running = False`.

It's intentionally minimal. No I/O, no awaits, no cancellation. The signal handler is not the place to do work — its job is to set state that the main loop can react to.

## Worker entrypoints

```python
async def _run_ingestion_worker() -> None:
    settings = Settings()
    setup_logging(settings.log_level)
    session = _create_boto3_session(settings)

    from shared.entrypoints.bootstrap import get_contract_intelligence_container

    container = await get_contract_intelligence_container()
    worker = SQSWorker(
        session,
        settings.sqs_contract_ingestion_queue_url,
        container,
        processor=ingestion_processor,
        endpoint_url=settings.aws_endpoint_url,
        worker_name="contract_ingestion_worker",
        use_heartbeat=True,
        heartbeat_interval=60,
        heartbeat_extension=120,
    )
    await worker.run()
```

One factory per queue. Differences across the three (`_run_ingestion_worker`, `_run_analysis_worker`, `_run_dlq_worker`) are tiny:
- Different queue URL
- Different processor module
- Different worker name (for log filtering)
- DLQ worker has `use_heartbeat=False` because it's just a status update — no long-running work to protect.

The deferred container import (`from shared.entrypoints.bootstrap import ...` inside the function) breaks an import cycle between the bootstrap module and the worker module.

```python
def _create_boto3_session(settings: Settings) -> aioboto3.Session:
    if settings.aws_endpoint_url:
        return aioboto3.Session(
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
        )
    return aioboto3.Session(region_name=settings.aws_region)
```

In LocalStack mode, pass dummy credentials explicitly. In production, let aioboto3 pick credentials from the environment / instance metadata / IRSA — we don't want to read static credentials from `Settings` in prod.

## `main()`

```python
def main() -> None:
    parser = argparse.ArgumentParser(description="Contract Intelligence SQS Worker")
    parser.add_argument("--queue", choices=["ingestion", "analysis", "dlq"], required=True)
    args = parser.parse_args()

    if args.queue == "ingestion":
        asyncio.run(_run_ingestion_worker())
    elif args.queue == "analysis":
        asyncio.run(_run_analysis_worker())
    elif args.queue == "dlq":
        asyncio.run(_run_dlq_worker())
```

Single entrypoint, one of three behaviors selected by `--queue`. In k8s, each Deployment uses the same image but a different `args` value, so we can run them as three separate pods scaled independently by KEDA based on each queue's depth.

## Mental model: a typical message lifecycle

```
1. Pod starts
   ├── main() → asyncio.run(_run_ingestion_worker())
   ├── Settings, logging, session, container created
   └── SQSWorker.run() begins

2. SQS client opened (once for the lifetime of the pod)
   └── async with self._session.client("sqs") as sqs

3. Signal handlers registered
   └── SIGTERM, SIGINT → _shutdown

4. Polling loop iteration 1
   ├── _poll() → SQS long-poll, returns 0 messages
   └── continue (loop again)

5. Polling loop iteration 2
   ├── _poll() → SQS returns 8 messages
   ├── 8 _bounded_process tasks created
   ├── 5 acquire semaphore immediately, 3 wait
   ├── For each running message:
   │     ├── clear_contextvars + bind_contextvars
   │     ├── start heartbeat task (if enabled)
   │     ├── processor.process_event(body, container)
   │     │     └── (calls into application services, UoW commits, etc.)
   │     ├── log message_processed with processing_seconds
   │     └── finally:
   │           ├── delete_message
   │           ├── heartbeat_task.cancel() + gather
   │           └── clear_contextvars
   └── gather() returns when all 8 finish

6. ...repeat polling indefinitely...

7. Pod receives SIGTERM (k8s rolling deploy)
   ├── _shutdown() runs as loop callback → _running = False
   ├── Current batch finishes its gather()
   ├── while loop exits
   ├── _drain() waits up to 30s for any stragglers
   ├── async with closes SQS client
   └── Process exits 0
```

## Why this design over alternatives

| Concern | What we did | What we avoided |
|---|---|---|
| Client reuse | One client for the worker's lifetime | Per-call `async with session.client()` (~100-300ms overhead/call) |
| Concurrency | Asyncio + Semaphore | Threads (botocore is not thread-safe; GIL contention) |
| Concurrency | Asyncio + Semaphore | Multiple processes (no benefit for I/O-bound work; memory overhead) |
| Backpressure | Semaphore bounds in-flight count | Unbounded `gather` (would drown downstream APIs) |
| Logging context | `contextvars` (asyncio-safe) | Thread-locals (broken under asyncio) or function args |
| Error isolation | Per-message try/except, return_exceptions=True | Letting one bad message kill the whole batch |
| Shutdown | Signal handler sets flag + drain on exit | Hard kill (in-flight messages would be lost or double-processed) |
| Visibility timeout | Heartbeat extension | Setting a huge static timeout (slow recovery on real failures) |

## Tuning knobs

These are the three you'll want to adjust based on observed behavior:

- **`max_concurrency`** — start at 5. Increase if downstream APIs (Reducto, OpenAI) can handle more parallel calls and the worker is the bottleneck. Decrease if you start hitting rate limits.
- **`heartbeat_interval` / `heartbeat_extension`** — defaults of 60s/120s suit most cases. If processing routinely takes >10 minutes, increase the extension to reduce the number of API calls.
- **`drain_timeout`** — match it to your k8s `terminationGracePeriodSeconds` minus a small buffer (e.g., 30s drain with 45s grace period).
