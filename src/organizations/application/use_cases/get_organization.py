from uuid import UUID

from organizations.application.ports.repositories.membership_repository import (
    MembershipRepository,
)
from organizations.application.ports.repositories.organization_repository import (
    OrganizationRepository,
)
from organizations.application.ports.repositories.user_repository import UserRepository
from organizations.domain.exceptions import (
    AuthorizationError,
    OrganizationNotFoundError,
    UserNotFoundError,
)
from organizations.domain.models.organization import Organization


class GetOrganization:
    def __init__(
        self,
        organization_repo: OrganizationRepository,
        user_repo: UserRepository,
        membership_repo: MembershipRepository,
    ) -> None:
        self.organization_repo = organization_repo
        self.user_repo = user_repo
        self.membership_repo = membership_repo

    async def execute(self, *, supabase_user_id: str, organization_id: UUID) -> Organization:
        user = await self.user_repo.get_by_supabase_id(supabase_user_id)
        if not user:
            raise UserNotFoundError(supabase_user_id)

        membership = await self.membership_repo.get_by_user_and_organization(
            user.id, organization_id
        )
        if not membership:
            raise AuthorizationError("Not authorized to access this organization")

        organization = await self.organization_repo.get_by_id(organization_id)
        if not organization:
            raise OrganizationNotFoundError(str(organization_id))

        return organization
