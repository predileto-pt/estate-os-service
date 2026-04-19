from uuid import UUID

from customers.application.ports.repositories.user_repository import UserRepository
from customers.domain.models.user import User


class InMemoryUserRepository(UserRepository):
    def __init__(self) -> None:
        self._users: dict[UUID, User] = {}

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self._users.get(user_id)

    async def get_by_supabase_id(self, supabase_user_id: str) -> User | None:
        for user in self._users.values():
            if user.supabase_user_id == supabase_user_id:
                return user
        return None

    async def get_by_email(self, email: str) -> User | None:
        for user in self._users.values():
            if user.email == email:
                return user
        return None

    async def save(self, user: User) -> User:
        self._users[user.id] = user
        return user

    async def update(self, user: User) -> User:
        self._users[user.id] = user
        return user
