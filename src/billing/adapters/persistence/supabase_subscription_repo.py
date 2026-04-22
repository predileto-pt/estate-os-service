from datetime import datetime
from uuid import UUID

from supabase import AsyncClient

from billing.application.ports.repositories.subscription_repository import (
    SubscriptionRepository,
)
from billing.domain.models.subscription import (
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
    SubscriptionType,
)


def _parse_ts(value: str) -> datetime:
    """Parse a Postgres-shaped ISO-8601 timestamp string into a datetime.

    Supabase's PostgREST JSON responses return `timestamptz` columns as
    strings like `2026-04-22T10:15:30.123456+00:00`. Python's
    `datetime.fromisoformat` handles that natively from 3.11+.
    """
    return datetime.fromisoformat(value)


def _parse_ts_optional(value: str | None) -> datetime | None:
    return None if value is None else _parse_ts(value)


class SupabaseSubscriptionRepository(SubscriptionRepository):
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    def _to_domain(self, row: dict) -> Subscription:
        return Subscription(
            id=UUID(row["id"]),
            organization_id=UUID(row["organization_id"]),
            plan=SubscriptionPlan(row["plan"]),
            type=SubscriptionType(row["type"]),
            status=SubscriptionStatus(row["status"]),
            stripe_customer_id=row.get("stripe_customer_id"),
            stripe_subscription_id=row.get("stripe_subscription_id"),
            stripe_price_id=row.get("stripe_price_id"),
            current_period_start=_parse_ts_optional(row.get("current_period_start")),
            current_period_end=_parse_ts_optional(row.get("current_period_end")),
            created_at=_parse_ts(row["created_at"]),
            updated_at=_parse_ts(row["updated_at"]),
        )

    def _to_row(self, sub: Subscription) -> dict:
        return {
            "id": str(sub.id),
            "organization_id": str(sub.organization_id),
            "plan": sub.plan.value,
            "type": sub.type.value,
            "status": sub.status.value,
            "stripe_customer_id": sub.stripe_customer_id,
            "stripe_subscription_id": sub.stripe_subscription_id,
            "stripe_price_id": sub.stripe_price_id,
            "current_period_start": (
                sub.current_period_start.isoformat() if sub.current_period_start else None
            ),
            "current_period_end": (
                sub.current_period_end.isoformat() if sub.current_period_end else None
            ),
        }

    async def get_by_id(self, subscription_id: UUID) -> Subscription | None:
        result = (
            await self._client.table("subscriptions")
            .select("*")
            .eq("id", str(subscription_id))
            .execute()
        )
        if not result.data:
            return None
        return self._to_domain(result.data[0])

    async def get_by_organization_id(self, organization_id: UUID) -> Subscription | None:
        result = (
            await self._client.table("subscriptions")
            .select("*")
            .eq("organization_id", str(organization_id))
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        return self._to_domain(result.data[0])

    async def get_by_stripe_customer_id(self, stripe_customer_id: str) -> Subscription | None:
        result = (
            await self._client.table("subscriptions")
            .select("*")
            .eq("stripe_customer_id", stripe_customer_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        return self._to_domain(result.data[0])

    async def save(self, subscription: Subscription) -> Subscription:
        result = (
            await self._client.table("subscriptions").insert(self._to_row(subscription)).execute()
        )
        return self._to_domain(result.data[0])

    async def update(self, subscription: Subscription) -> Subscription:
        row = self._to_row(subscription)
        result = (
            await self._client.table("subscriptions")
            .update(row)
            .eq("id", str(subscription.id))
            .execute()
        )
        return self._to_domain(result.data[0])
