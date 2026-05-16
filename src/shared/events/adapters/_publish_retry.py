"""Bounded-retry wrapper for RabbitMQ event + command publishes.

Both `RabbitMQEventPublisher.publish` and `RabbitMQCommandPublisher.send`
go through `publish_with_retry`. The wrapper absorbs transient AMQP
failures (reconnect windows, channel-not-yet-open races after broker
restarts) and surfaces a terminal `PublishFailedAfterRetry` with rich
structured logs so direct callers don't need their own logging
boilerplate.

See `.claude/specs/estate-os-service/active/rabbitmq-publish-reliability.md`
for the rationale and the retriable / non-retriable error matrix.

Retriable (sleep + retry):
  - RuntimeError("Connection was not opened") — message-matched
  - aio_pika.exceptions.AMQPConnectionError
  - aio_pika.exceptions.ChannelInvalidStateError

Non-retriable (re-raise immediately):
  - aio_pika.exceptions.DeliveryError (mandatory-publish unroutable)
  - aio_pika.exceptions.AMQPChannelError on declare (broker rejected)
  - aio_pika.exceptions.ProbableAuthenticationError
  - Anything else (non-AMQP errors are caller bugs, not transport problems)

Exception ordering inside the helper is load-bearing because:
  - ChannelInvalidStateError inherits from RuntimeError (we want it
    retried regardless of message; the RuntimeError filter only
    accepts "not opened").
  - ProbableAuthenticationError inherits from AMQPConnectionError
    (auth failures are permanent; must be caught before the connection
    retry branch).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import structlog
from aio_pika.exceptions import (
    AMQPChannelError,
    AMQPConnectionError,
    AMQPError,
    ChannelInvalidStateError,
    DeliveryError,
    ProbableAuthenticationError,
)

log = structlog.get_logger()

_BACKOFFS_SECONDS = (0.5, 1.0, 2.0)
_MAX_ATTEMPTS = 3
_CONNECTION_NOT_OPENED_MARKER = "Connection was not opened"


class PublishFailedAfterRetry(AMQPError):
    """Raised when the retry budget exhausts.

    Subclasses `aio_pika.exceptions.AMQPError` so callers using
    `except AMQPError` naturally catch it; `except Exception` works too.
    The last underlying exception is chained via `__cause__`.
    """

    def __init__(
        self,
        *,
        event_id: str,
        event_type: str,
        sink: str,
        attempts: int,
    ) -> None:
        self.event_id = event_id
        self.event_type = event_type
        self.sink = sink
        self.attempts = attempts
        super().__init__(
            f"publish failed for event_id={event_id} event_type={event_type} "
            f"sink={sink} after {attempts} attempts"
        )


async def publish_with_retry(
    body_fn: Callable[[], Awaitable[None]],
    *,
    event_id: str,
    event_type: str,
    sink: str,
) -> None:
    """Run `body_fn` with bounded retry on transient AMQP failures.

    `sink` is the exchange name (event publisher) or queue name (command
    publisher) — included in structured logs so a single log search by
    sink surfaces all related failures.

    Raises `PublishFailedAfterRetry` after `_MAX_ATTEMPTS` exhaustion or
    re-raises immediately for non-retriable errors.
    """
    last_error: BaseException | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            await body_fn()
            return
        # --- Non-retriable, ordered before their parent classes ---------
        except ProbableAuthenticationError:
            # Subclass of AMQPConnectionError but always permanent.
            raise
        except DeliveryError:
            # `mandatory=True` returned the message because no queue is
            # bound. Permanent misconfiguration (typo'd routing-key /
            # queue name). Retrying just hides the bug.
            raise
        except AMQPChannelError:
            # Raised during declare_exchange / declare_queue when the
            # broker rejects the declaration (e.g., re-declaring with
            # mismatched durability). Permanent.
            raise
        # --- Retriable -------------------------------------------------
        except ChannelInvalidStateError as e:
            # Subclass of RuntimeError. Catch first so it doesn't fall
            # through to the RuntimeError filter (which only matches
            # "Connection was not opened").
            last_error = e
        except AMQPConnectionError as e:
            last_error = e
        except RuntimeError as e:
            if _CONNECTION_NOT_OPENED_MARKER not in str(e):
                raise
            last_error = e

        log.warning(
            "event_publish_attempt_failed",
            event_id=event_id,
            event_type=event_type,
            sink=sink,
            attempt=attempt,
            error_class=type(last_error).__name__,
            error=str(last_error),
        )

        if attempt == _MAX_ATTEMPTS:
            break
        await asyncio.sleep(_BACKOFFS_SECONDS[attempt - 1])

    log.error(
        "event_publish_failed",
        event_id=event_id,
        event_type=event_type,
        sink=sink,
        attempts=_MAX_ATTEMPTS,
        error_class=type(last_error).__name__,
        error=str(last_error),
    )
    raise PublishFailedAfterRetry(
        event_id=event_id,
        event_type=event_type,
        sink=sink,
        attempts=_MAX_ATTEMPTS,
    ) from last_error
