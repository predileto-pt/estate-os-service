from uuid import UUID

from organizations.application.ports.repositories.invitation_repository import (
    InvitationRepository,
)
from organizations.application.ports.repositories.membership_repository import (
    MembershipRepository,
)
from organizations.application.ports.repositories.user_repository import UserRepository
from organizations.domain.exceptions import (
    AuthorizationError,
    UserNotFoundError,
)
from organizations.domain.models.invitation import Invitation


class ListInvitations:
    def __init__(
        self,
        invitation_repo: InvitationRepository,
        membership_repo: MembershipRepository,
        user_repo: UserRepository,
    ) -> None:
        self.invitation_repo = invitation_repo
        self.membership_repo = membership_repo
        self.user_repo = user_repo

    async def execute(self, *, supabase_user_id: str, organization_id: UUID) -> list[Invitation]:
        user = await self.user_repo.get_by_supabase_id(supabase_user_id)
        if not user:
            raise UserNotFoundError(supabase_user_id)

        membership = await self.membership_repo.get_by_user_and_organization(
            user.id, organization_id
        )
        if not membership:
            raise AuthorizationError("Not a member of this organization")

        return await self.invitation_repo.list_by_organization(organization_id)
