from uuid import UUID

from supabase import AsyncClient

from customer_management.application.ports.repositories.subscription_repository import (
    SubscriptionRepository,
)
from customer_management.domain.models.subscription import (
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
    SubscriptionType,
)


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
            stripe_subscription_id=row.get("stripe_subscription_id"),
            stripe_price_id=row.get("stripe_price_id"),
            current_period_start=row.get("current_period_start"),
            current_period_end=row.get("current_period_end"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _to_row(self, sub: Subscription) -> dict:
        return {
            "id": str(sub.id),
            "organization_id": str(sub.organization_id),
            "plan": sub.plan.value,
            "type": sub.type.value,
            "status": sub.status.value,
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
