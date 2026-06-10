from billing.application.ports.repositories.stripe_webhook_events_repository import (
    StripeWebhookEventsRepository,
)


class InMemoryStripeWebhookEventsRepository(StripeWebhookEventsRepository):
    def __init__(self) -> None:
        # Store (event_type, payload) so tests can assert what was recorded.
        self._seen: dict[str, tuple[str, dict]] = {}

    async def has_processed(self, *, event_id: str) -> bool:
        return event_id in self._seen

    async def try_mark_processed(self, *, event_id: str, event_type: str, payload: dict) -> bool:
        if event_id in self._seen:
            return False
        self._seen[event_id] = (event_type, payload)
        return True
