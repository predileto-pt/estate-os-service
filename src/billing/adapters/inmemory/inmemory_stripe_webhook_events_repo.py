from billing.application.ports.repositories.stripe_webhook_events_repository import (
    StripeWebhookEventsRepository,
)


class InMemoryStripeWebhookEventsRepository(StripeWebhookEventsRepository):
    def __init__(self) -> None:
        self._seen: set[str] = set()

    async def try_mark_processed(self, *, event_id: str, event_type: str) -> bool:
        if event_id in self._seen:
            return False
        self._seen.add(event_id)
        return True
