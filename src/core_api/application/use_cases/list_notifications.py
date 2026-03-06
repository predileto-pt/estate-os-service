from uuid import UUID

from core_api.application.ports.repositories.notification_repository import NotificationRepository
from core_api.domain.models.notification import Notification


class ListNotifications:
    def __init__(self, notification_repo: NotificationRepository) -> None:
        self.notification_repo = notification_repo

    async def execute(
        self, *, user_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[Notification]:
        return await self.notification_repo.list_by_user_id(
            user_id, limit=limit, offset=offset
        )
