from datetime import datetime, timezone
from uuid import UUID, uuid4

import structlog

from customer_management.application.ports.repositories.notification_repository import (
    NotificationRepository,
)
from customer_management.domain.models.notification import Notification, NotificationStatus

log = structlog.get_logger()


class SendNotification:
    def __init__(
        self,
        notification_repo: NotificationRepository,
    ) -> None:
        self.notification_repo = notification_repo

    async def execute(
        self,
        *,
        user_id: UUID,
        title: str,
        message: str,
        channel: str = "in_app",
    ) -> Notification:
        now = datetime.now(timezone.utc)
        notification = Notification(
            id=uuid4(),
            user_id=user_id,
            title=title,
            message=message,
            status=NotificationStatus.UNREAD,
            channel=channel,
            created_at=now,
            read_at=None,
        )
        notification = await self.notification_repo.save(notification)

        log.info("notification_sent", notification_id=str(notification.id))
        return notification
