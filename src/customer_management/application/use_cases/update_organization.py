from uuid import UUID

from customer_management.application.ports.repositories.membership_repository import (
    MembershipRepository,
)
from customer_management.application.ports.repositories.organization_repository import (
    OrganizationRepository,
)
from customer_management.application.ports.repositories.user_repository import UserRepository
from customer_management.domain.exceptions import (
    InsufficientPermissionError,
    OrganizationNotFoundError,
    UserNotFoundError,
)
from customer_management.domain.models.authorization import has_permission
from customer_management.domain.models.organization import Organization


class UpdateOrganization:
    def __init__(
        self,
        organization_repo: OrganizationRepository,
        user_repo: UserRepository,
        membership_repo: MembershipRepository,
    ) -> None:
        self.organization_repo = organization_repo
        self.user_repo = user_repo
        self.membership_repo = membership_repo

    async def execute(
        self,
        *,
        organization_id: UUID,
        supabase_user_id: str,
        name: str | None = None,
        nif: str | None = None,
        address: str | None = None,
    ) -> Organization:
        user = await self.user_repo.get_by_supabase_id(supabase_user_id)
        if not user:
            raise UserNotFoundError(supabase_user_id)

        membership = await self.membership_repo.get_by_user_and_organization(
            user.id, organization_id
        )
        if not membership or not has_permission(membership.role, "organization.update"):
            raise InsufficientPermissionError("organization.update")

        organization = await self.organization_repo.get_by_id(organization_id)
        if not organization:
            raise OrganizationNotFoundError(str(organization_id))

        organization.update(name=name, nif=nif, address=address)

        return await self.organization_repo.update(organization)
