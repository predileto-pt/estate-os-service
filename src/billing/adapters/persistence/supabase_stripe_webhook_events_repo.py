"""PostgREST-backed idempotency + audit store for Stripe webhook events.

Uses Supabase's `.upsert(..., on_conflict='event_id', ignore_duplicates=True)`
which compiles to `INSERT ... ON CONFLICT ... DO NOTHING RETURNING *` on the
Postgres side — one atomic statement. `result.data` comes back populated
for new rows and empty for duplicates, which is exactly the "was this new?"
signal the port contract wants.
"""

from supabase import AsyncClient

from billing.application.ports.repositories.stripe_webhook_events_repository import (
    StripeWebhookEventsRepository,
)


class SupabaseStripeWebhookEventsRepository(StripeWebhookEventsRepository):
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def has_processed(self, *, event_id: str) -> bool:
        result = (
            await self._client.table("stripe_webhook_events")
            .select("event_id")
            .eq("event_id", event_id)
            .limit(1)
            .execute()
        )
        return bool(result.data)

    async def try_mark_processed(self, *, event_id: str, event_type: str, payload: dict) -> bool:
        result = (
            await self._client.table("stripe_webhook_events")
            .upsert(
                {
                    "event_id": event_id,
                    "event_type": event_type,
                    "payload": payload,
                },
                on_conflict="event_id",
                ignore_duplicates=True,
            )
            .execute()
        )
        # `.upsert(..., ignore_duplicates=True)` returns the inserted row(s)
        # in `data`. A duplicate returns an empty list — that's our signal.
        return bool(result.data)
