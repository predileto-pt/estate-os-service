"""Tests for the `publish_with_retry` helper.

Covers the retriable / non-retriable error matrix, structured-log
emission, and the emit_* swallow contract.

See `.claude/specs/estate-os-service/active/rabbitmq-publish-reliability.md`
for the design.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from unittest.mock import patch

import pytest
import structlog
from aio_pika.exceptions import (
    AMQPChannelError,
    AMQPConnectionError,
    AMQPError,
    ChannelInvalidStateError,
    DeliveryError,
    ProbableAuthenticationError,
)

from shared.events.adapters._publish_retry import (
    PublishFailedAfterRetry,
    publish_with_retry,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _flaky_body(
    raises: list[BaseException | None],
) -> tuple[Callable[[], Awaitable[None]], list[int]]:
    """Build a body callable that emits the next item from `raises` on
    each call. `None` means "succeed". Returns the body + a list whose
    only element is the call count so tests can assert on it.

    Example: `_flaky_body([err1, err2, None])` raises err1, err2, then
    succeeds on the third call.
    """
    calls = [0]

    async def body() -> None:
        idx = calls[0]
        calls[0] += 1
        if idx >= len(raises):
            return
        exc = raises[idx]
        if exc is not None:
            raise exc

    return body, calls


@pytest.fixture(autouse=True)
def _instant_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip real sleeps — the retry logic is deterministic; we don't need
    to wait the full 3.5s in tests."""

    async def _noop(_seconds: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _noop)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_succeeds_on_first_attempt() -> None:
    body, calls = _flaky_body([None])
    await publish_with_retry(body, event_id="evt-1", event_type="X.v1", sink="exchange")
    assert calls[0] == 1


# ---------------------------------------------------------------------------
# Retriable paths
# ---------------------------------------------------------------------------


async def test_retries_on_connection_not_opened_then_succeeds() -> None:
    body, calls = _flaky_body([RuntimeError("Connection was not opened"), None])
    await publish_with_retry(body, event_id="evt-1", event_type="X.v1", sink="ex")
    assert calls[0] == 2


async def test_retries_on_amqp_connection_error() -> None:
    body, calls = _flaky_body([AMQPConnectionError("link broken"), None])
    await publish_with_retry(body, event_id="evt-1", event_type="X.v1", sink="ex")
    assert calls[0] == 2


async def test_retries_on_channel_invalid_state() -> None:
    """ChannelInvalidStateError is a RuntimeError subclass — must be
    caught regardless of its message, so the dedicated except clause
    has to run before the message-filtered RuntimeError branch."""
    body, calls = _flaky_body([ChannelInvalidStateError("not open"), None])
    await publish_with_retry(body, event_id="evt-1", event_type="X.v1", sink="ex")
    assert calls[0] == 2


# ---------------------------------------------------------------------------
# Terminal exhaustion
# ---------------------------------------------------------------------------


async def test_terminal_after_three_attempts() -> None:
    inner = AMQPConnectionError("link broken")
    body, calls = _flaky_body([inner, inner, inner])

    with pytest.raises(PublishFailedAfterRetry) as exc_info:
        await publish_with_retry(body, event_id="evt-1", event_type="X.v1", sink="ex")

    assert calls[0] == 3
    err = exc_info.value
    assert err.event_id == "evt-1"
    assert err.event_type == "X.v1"
    assert err.sink == "ex"
    assert err.attempts == 3
    assert err.__cause__ is inner


async def test_publish_failed_after_retry_is_amqp_error() -> None:
    """`except AMQPError` must catch terminal failures so existing
    callers using that catch don't need to add another handler."""
    body, _ = _flaky_body(
        [AMQPConnectionError("x"), AMQPConnectionError("x"), AMQPConnectionError("x")]
    )
    with pytest.raises(AMQPError):
        await publish_with_retry(body, event_id="e", event_type="t", sink="s")


# ---------------------------------------------------------------------------
# Non-retriable paths
# ---------------------------------------------------------------------------


async def test_does_not_retry_delivery_error() -> None:
    """DeliveryError signals a permanent routing-key / queue typo.
    Retrying just hides the bug."""
    body, calls = _flaky_body([DeliveryError([], "no route"), None])

    with pytest.raises(DeliveryError):
        await publish_with_retry(body, event_id="e", event_type="t", sink="s")

    assert calls[0] == 1


async def test_does_not_retry_channel_declaration_error() -> None:
    """AMQPChannelError on declare means the broker rejected the
    declaration (e.g., mismatched durability) — permanent."""
    body, calls = _flaky_body([AMQPChannelError("mismatched"), None])

    with pytest.raises(AMQPChannelError):
        await publish_with_retry(body, event_id="e", event_type="t", sink="s")

    assert calls[0] == 1


async def test_does_not_retry_probable_authentication_error() -> None:
    """ProbableAuthenticationError subclasses AMQPConnectionError —
    must be caught before the retry branch."""
    body, calls = _flaky_body([ProbableAuthenticationError("bad creds"), None])

    with pytest.raises(ProbableAuthenticationError):
        await publish_with_retry(body, event_id="e", event_type="t", sink="s")

    assert calls[0] == 1


async def test_does_not_retry_runtime_error_without_marker() -> None:
    """RuntimeError without "Connection was not opened" is not a
    transport problem — bubble up."""
    body, calls = _flaky_body([RuntimeError("something else"), None])

    with pytest.raises(RuntimeError, match="something else"):
        await publish_with_retry(body, event_id="e", event_type="t", sink="s")

    assert calls[0] == 1


async def test_does_not_retry_arbitrary_exception() -> None:
    """Non-AMQP exceptions are caller bugs, not transport problems."""
    body, calls = _flaky_body([ValueError("oops"), None])

    with pytest.raises(ValueError, match="oops"):
        await publish_with_retry(body, event_id="e", event_type="t", sink="s")

    assert calls[0] == 1


# ---------------------------------------------------------------------------
# Structured logging contract
# ---------------------------------------------------------------------------


async def test_structured_logs_carry_event_metadata() -> None:
    inner = AMQPConnectionError("link broken")
    body, _ = _flaky_body([inner, inner, inner])

    with structlog.testing.capture_logs() as captured:
        with pytest.raises(PublishFailedAfterRetry):
            await publish_with_retry(
                body, event_id="evt-7", event_type="PROPERTY_UPDATED.v1", sink="domain-events"
            )

    attempt_logs = [d for d in captured if d.get("event") == "event_publish_attempt_failed"]
    terminal_logs = [d for d in captured if d.get("event") == "event_publish_failed"]

    assert len(attempt_logs) == 3
    assert len(terminal_logs) == 1

    for d in attempt_logs:
        assert d["event_id"] == "evt-7"
        assert d["event_type"] == "PROPERTY_UPDATED.v1"
        assert d["sink"] == "domain-events"
        assert d["error_class"] == "AMQPConnectionError"
        assert "error" in d
        assert "attempt" in d
        assert d["log_level"] == "warning"

    t = terminal_logs[0]
    assert t["event_id"] == "evt-7"
    assert t["event_type"] == "PROPERTY_UPDATED.v1"
    assert t["sink"] == "domain-events"
    assert t["attempts"] == 3
    assert t["error_class"] == "AMQPConnectionError"
    assert t["log_level"] == "error"


# ---------------------------------------------------------------------------
# Backoff schedule
# ---------------------------------------------------------------------------


async def test_backoff_schedule_is_0_5_1_2_seconds() -> None:
    """Sleeps between attempts: 0.5s, 1.0s. No sleep after the final
    attempt (we'd just raise). Total budget = 1.5s of sleep + body time."""
    seen_sleeps: list[float] = []

    async def _capture(seconds: float) -> None:
        seen_sleeps.append(seconds)

    with patch("asyncio.sleep", _capture):
        inner = AMQPConnectionError("x")
        body, _ = _flaky_body([inner, inner, inner])
        with pytest.raises(PublishFailedAfterRetry):
            await publish_with_retry(body, event_id="e", event_type="t", sink="s")

    assert seen_sleeps == [0.5, 1.0]


# ---------------------------------------------------------------------------
# emit_* swallow contract
# ---------------------------------------------------------------------------


def test_publish_failed_after_retry_is_swallowed_by_emit_wrappers() -> None:
    """The existing `emit_*` helpers all do `try / except Exception:
    log.exception(...)`. Our terminal exception subclasses `AMQPError`
    which itself is an `Exception`, so the swallow contract still holds.

    Asserted as a class-level invariant rather than a full integration
    walkthrough — the `emit_*` helpers eagerly serialize the aggregate
    before reaching the publish call, and constructing valid Property /
    ScreeningSubmission / etc. fixtures here would couple this test to
    every emit_* call site's domain model."""
    err = PublishFailedAfterRetry(event_id="e", event_type="t", sink="s", attempts=3)
    assert isinstance(err, Exception)
    assert isinstance(err, AMQPError)
