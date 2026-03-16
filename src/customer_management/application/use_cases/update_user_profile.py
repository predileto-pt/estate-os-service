from uuid import UUID

from customer_management.application.ports.repositories.user_repository import UserRepository
from customer_management.domain.exceptions import UserNotFoundError
from customer_management.domain.models.user import User
from customer_management.domain.models.value_objects import PhoneNumber


class UpdateUserProfile:
    def __init__(self, user_repo: UserRepository) -> None:
        self.user_repo = user_repo

    async def execute(
        self,
        *,
        user_id: UUID,
        name: str | None = None,
        phone: PhoneNumber | None = None,
    ) -> User:
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise UserNotFoundError(str(user_id))

        user.update_profile(name=name, phone=phone)

        return await self.user_repo.update(user)
