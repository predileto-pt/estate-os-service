from abc import ABC, abstractmethod
from uuid import UUID

from customer_management.domain.models.notification import Notification


class NotificationRepository(ABC):
    @abstractmethod
    async def get_by_id(self, notification_id: UUID) -> Notification | None: ...

    @abstractmethod
    async def list_by_user_id(
        self, user_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> list[Notification]: ...

    @abstractmethod
    async def save(self, notification: Notification) -> Notification: ...

    @abstractmethod
    async def mark_as_read(self, notification_ids: list[UUID], user_id: UUID) -> int: ...
