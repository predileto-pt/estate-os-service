from uuid import UUID

from customers.application.ports.repositories.portal_user_repository import (
    PortalUserRepository,
)
from customers.domain.models.portal_user import PortalUser


class InMemoryPortalUserRepository(PortalUserRepository):
    def __init__(self) -> None:
        self._users: dict[UUID, PortalUser] = {}

    async def get_by_id(self, user_id: UUID) -> PortalUser | None:
        return self._users.get(user_id)

    async def get_by_supabase_id(self, supabase_user_id: str) -> PortalUser | None:
        for user in self._users.values():
            if user.supabase_user_id == supabase_user_id:
                return user
        return None

    async def get_by_email(self, email: str) -> PortalUser | None:
        for user in self._users.values():
            if user.email == email:
                return user
        return None

    async def save(self, user: PortalUser) -> PortalUser:
        self._users[user.id] = user
        return user
