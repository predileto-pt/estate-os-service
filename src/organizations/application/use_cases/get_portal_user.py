from organizations.application.ports.repositories.portal_user_repository import (
    PortalUserRepository,
)
from organizations.domain.exceptions import PortalUserNotFoundError
from organizations.domain.models.portal_user import PortalUser


class GetPortalUser:
    def __init__(self, portal_user_repo: PortalUserRepository) -> None:
        self.portal_user_repo = portal_user_repo

    async def execute(self, *, supabase_user_id: str) -> PortalUser:
        user = await self.portal_user_repo.get_by_supabase_id(supabase_user_id)
        if not user:
            raise PortalUserNotFoundError(supabase_user_id)
        return user
