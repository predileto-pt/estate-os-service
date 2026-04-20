from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from billing.adapters.database.models import StripeWebhookEventModel
from billing.application.ports.repositories.stripe_webhook_events_repository import (
    StripeWebhookEventsRepository,
)


class SqlAlchemyStripeWebhookEventsRepository(StripeWebhookEventsRepository):
    """Postgres-backed idempotency store.

    Uses `INSERT ... ON CONFLICT DO NOTHING` so the check-and-mark is a
    single atomic statement. `rowcount` of 1 means the row was new (we
    should apply side effects); 0 means a duplicate (caller should ack
    and skip).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def try_mark_processed(self, *, event_id: str, event_type: str) -> bool:
        stmt = (
            insert(StripeWebhookEventModel)
            .values(event_id=event_id, event_type=event_type)
            .on_conflict_do_nothing(index_elements=["event_id"])
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return (result.rowcount or 0) > 0
