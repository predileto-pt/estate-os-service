from datetime import datetime, timezone
from uuid import UUID, uuid4

import structlog

from core_api.application.ports.event_bus import EventBus
from core_api.application.ports.repositories.notification_repository import NotificationRepository
from core_api.domain.events import NotificationSent
from core_api.domain.models.notification import Notification, NotificationStatus

log = structlog.get_logger()


class SendNotification:
    def __init__(
        self,
        notification_repo: NotificationRepository,
        event_bus: EventBus,
    ) -> None:
        self.notification_repo = notification_repo
        self.event_bus = event_bus

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

        await self.event_bus.publish(
            NotificationSent(
                notification_id=notification.id,
                user_id=user_id,
                channel=channel,
            )
        )

        log.info("notification_sent", notification_id=str(notification.id))
        return notification
