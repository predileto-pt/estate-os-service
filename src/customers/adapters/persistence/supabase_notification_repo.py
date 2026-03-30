from datetime import datetime, timezone
from uuid import UUID

from supabase import AsyncClient

from customers.application.ports.repositories.notification_repository import (
    NotificationRepository,
)
from customers.domain.models.notification import Notification, NotificationStatus


class SupabaseNotificationRepository(NotificationRepository):
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    def _to_domain(self, row: dict) -> Notification:
        return Notification(
            id=UUID(row["id"]),
            user_id=UUID(row["user_id"]),
            title=row["title"],
            message=row["message"],
            status=NotificationStatus(row["status"]),
            channel=row["channel"],
            created_at=row["created_at"],
            read_at=row.get("read_at"),
        )

    def _to_row(self, n: Notification) -> dict:
        return {
            "id": str(n.id),
            "user_id": str(n.user_id),
            "title": n.title,
            "message": n.message,
            "status": n.status.value,
            "channel": n.channel,
        }

    async def get_by_id(self, notification_id: UUID) -> Notification | None:
        result = (
            await self._client.table("notifications")
            .select("*")
            .eq("id", str(notification_id))
            .execute()
        )
        if not result.data:
            return None
        return self._to_domain(result.data[0])

    async def list_by_user_id(
        self, user_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> list[Notification]:
        result = (
            await self._client.table("notifications")
            .select("*")
            .eq("user_id", str(user_id))
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        return [self._to_domain(row) for row in result.data]

    async def save(self, notification: Notification) -> Notification:
        result = (
            await self._client.table("notifications").insert(self._to_row(notification)).execute()
        )
        return self._to_domain(result.data[0])

    async def mark_as_read(self, notification_ids: list[UUID], user_id: UUID) -> int:
        str_ids = [str(nid) for nid in notification_ids]
        now = datetime.now(timezone.utc).isoformat()
        result = (
            await self._client.table("notifications")
            .update({"status": "read", "read_at": now})
            .in_("id", str_ids)
            .eq("user_id", str(user_id))
            .execute()
        )
        return len(result.data)
