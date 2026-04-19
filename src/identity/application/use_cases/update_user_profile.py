from uuid import UUID

from identity.application.ports.repositories.user_repository import UserRepository
from identity.domain.exceptions import UserNotFoundError
from identity.domain.models.user import User
from identity.domain.value_objects import PhoneNumber


class UpdateUserProfile:
    _SENTINEL = object()

    def __init__(self, user_repo: UserRepository) -> None:
        self.user_repo = user_repo

    async def execute(
        self,
        *,
        user_id: UUID,
        name: str | None = None,
        phone: PhoneNumber | None | object = _SENTINEL,
    ) -> User:
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise UserNotFoundError(str(user_id))

        if phone is UpdateUserProfile._SENTINEL:
            user.update_profile(name=name)
        else:
            user.update_profile(name=name, phone=phone)  # type: ignore[arg-type]

        return await self.user_repo.update(user)
