from datetime import datetime, timezone
from uuid import UUID

from customer_management.application.ports.repositories.notification_repository import (
    NotificationRepository,
)
from customer_management.domain.models.notification import Notification, NotificationStatus


class InMemoryNotificationRepository(NotificationRepository):
    def __init__(self) -> None:
        self._notifications: dict[UUID, Notification] = {}

    async def get_by_id(self, notification_id: UUID) -> Notification | None:
        return self._notifications.get(notification_id)

    async def list_by_user_id(
        self, user_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> list[Notification]:
        user_notifications = sorted(
            [n for n in self._notifications.values() if n.user_id == user_id],
            key=lambda n: n.created_at,
            reverse=True,
        )
        return user_notifications[offset : offset + limit]

    async def save(self, notification: Notification) -> Notification:
        self._notifications[notification.id] = notification
        return notification

    async def mark_as_read(self, notification_ids: list[UUID], user_id: UUID) -> int:
        count = 0
        now = datetime.now(timezone.utc)
        for nid in notification_ids:
            notification = self._notifications.get(nid)
            if notification and notification.user_id == user_id:
                notification.status = NotificationStatus.READ
                notification.read_at = now
                count += 1
        return count
