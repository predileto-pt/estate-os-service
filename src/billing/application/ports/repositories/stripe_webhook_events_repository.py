from abc import ABC, abstractmethod


class StripeWebhookEventsRepository(ABC):
    """Idempotency + audit store for Stripe webhook events.

    `has_processed` reports whether an event_id has already been applied,
    so the handler can no-op a replay *before* running side effects.

    `try_mark_processed` atomically records an event_id along with the
    full decoded event envelope; returns True if it was new, False if the
    id was already seen. The handler calls it only *after* side effects
    succeed, so a failed/skipped apply leaves the event un-acked and
    Stripe retries it (rather than the event being burned on receipt).

    `payload` is the complete event JSON as a Python dict — the same
    shape Stripe sends on the webhook. Retained for audit and local
    replay / debugging.
    """

    @abstractmethod
    async def has_processed(self, *, event_id: str) -> bool: ...

    @abstractmethod
    async def try_mark_processed(
        self, *, event_id: str, event_type: str, payload: dict
    ) -> bool: ...
