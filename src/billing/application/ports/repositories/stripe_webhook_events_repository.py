from abc import ABC, abstractmethod


class StripeWebhookEventsRepository(ABC):
    """Idempotency store for Stripe webhook event IDs.

    `try_mark_processed` atomically records an event_id; returns True if
    it was new (caller should apply side effects), False if the id was
    already seen (caller should no-op and 200 back to Stripe).
    """

    @abstractmethod
    async def try_mark_processed(self, *, event_id: str, event_type: str) -> bool: ...
