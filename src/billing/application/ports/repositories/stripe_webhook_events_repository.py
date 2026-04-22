from abc import ABC, abstractmethod


class StripeWebhookEventsRepository(ABC):
    """Idempotency + audit store for Stripe webhook events.

    `try_mark_processed` atomically records an event_id along with the
    full decoded event envelope; returns True if it was new (caller
    should apply side effects), False if the id was already seen
    (caller should no-op and 200 back to Stripe).

    `payload` is the complete event JSON as a Python dict — the same
    shape Stripe sends on the webhook. Retained for audit and local
    replay / debugging.
    """

    @abstractmethod
    async def try_mark_processed(
        self, *, event_id: str, event_type: str, payload: dict
    ) -> bool: ...
