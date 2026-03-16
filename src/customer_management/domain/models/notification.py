from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID


class NotificationStatus(str, Enum):
    UNREAD = "unread"
    READ = "read"


@dataclass
class Notification:
    id: UUID
    user_id: UUID
    title: str
    message: str
    status: NotificationStatus
    channel: str  # "email", "in_app"
    created_at: datetime
    read_at: datetime | None

    def mark_read(self) -> None:
        self.status = NotificationStatus.READ
        self.read_at = datetime.now(timezone.utc)
