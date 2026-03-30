from uuid import UUID

from customers.application.ports.repositories.notification_repository import (
    NotificationRepository,
)


class MarkNotificationsRead:
    def __init__(self, notification_repo: NotificationRepository) -> None:
        self.notification_repo = notification_repo

    async def execute(self, *, notification_ids: list[UUID], user_id: UUID) -> int:
        return await self.notification_repo.mark_as_read(notification_ids, user_id)
