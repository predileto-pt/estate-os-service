"""Lambda handler factory — drives `EventRouter` from an SQS trigger.

One Lambda invocation handles exactly one SQS record (we configure
`batch_size = 1` on every `aws_lambda_event_source_mapping`). AWS scales
by adding parallel invocations up to the function's reserved concurrency
cap; in-process concurrency is irrelevant.

Failure semantics: handler raises → invocation marked failed → SQS
redrives the single record per the queue's `maxReceiveCount` → DLQ.
Equivalent to `SQSWorker`'s nack-and-rely-on-visibility-timeout flow.
With `batch_size = 1` there is no need for `batchItemFailures`.

Each invocation:
- Calls `asyncio.run(...)` with a fresh event loop. No persistent state
  across warm invocations — the listings/property containers are
  rebuilt each call. This trades ~50-200 ms of pool/client setup
  per invocation for trivial correctness (no cross-loop client binding,
  no stale-TLS recovery). See ADR-018.
- Unwraps the SNS envelope when present (mirrors
  `SQSMessage.__init__` in `sqs_message_consumer.py`).
- The `EventRouter` argument is constructed once per cold start by the
  per-context entrypoint and reused across warm invocations as
  module-level state. Routers carry no async resources.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from shared.events.base import DomainEvent
from shared.events.router import EventRouter

log = structlog.get_logger()

# Context factory — invoked per Lambda call to produce the dispatch
# context. Async so containers that open async resources (Supabase
# client, SQLAlchemy engine) can be awaited.
ContextFactory = Callable[[], Awaitable[Any]]
LambdaHandler = Callable[[dict[str, Any], Any], None]


def _parse_record(record: dict[str, Any]) -> DomainEvent:
    """Decode the SQS record body into a `DomainEvent`.

    Handles both shapes:
    - SNS→SQS subscription (raw_message_delivery=true) — body IS the
      DomainEvent JSON.
    - SNS→SQS without raw delivery — body is the SNS envelope dict
      containing a stringified `Message` field. We unwrap it.
    """
    body = json.loads(record["body"])
    event_json = (
        json.loads(body["Message"]) if isinstance(body, dict) and "Message" in body else body
    )
    return DomainEvent.from_dict(event_json)


def make_handler(router: EventRouter, build_context: ContextFactory) -> LambdaHandler:
    """Build a sync Lambda handler that dispatches a single SQS record."""

    async def _dispatch_one(record: dict[str, Any]) -> None:
        event = _parse_record(record)
        context = await build_context()
        await router.dispatch(event, context)

    def handler(event: dict[str, Any], _context: Any) -> None:
        records = event.get("Records") if isinstance(event, dict) else None
        if not records:
            raise ValueError(
                "Lambda invoked without SQS records — refusing to process. "
                "This handler is only valid behind an SQS event source mapping."
            )
        if len(records) > 1:
            # `batch_size = 1` is set in terraform; receiving more than one
            # means a misconfigured event source mapping. Fail loud rather
            # than silently process only the first.
            raise ValueError(
                f"Lambda invoked with {len(records)} records but expects 1. "
                "Check the event source mapping's batch_size."
            )
        record = records[0]
        log.info(
            "lambda_invocation_started",
            message_id=record.get("messageId"),
        )
        asyncio.run(_dispatch_one(record))
        log.info(
            "lambda_invocation_completed",
            message_id=record.get("messageId"),
        )

    return handler
