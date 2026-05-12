from uuid import UUID

from organizations.application.ports.repositories.membership_repository import (
    MembershipRepository,
)
from organizations.application.ports.repositories.organization_repository import (
    OrganizationRepository,
)
from organizations.application.ports.repositories.user_repository import UserRepository
from organizations.domain.exceptions import (
    InsufficientPermissionError,
    OrganizationNotFoundError,
)
from organizations.domain.models.authorization import has_permission
from organizations.domain.models.organization import Organization
from organizations.domain.value_objects import PhoneNumber


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
        requester_user_id: UUID,
        name: str | None = None,
        nif: str | None = None,
        address: str | None = None,
        email: str | None = None,
        phone: PhoneNumber | None = None,
    ) -> Organization:
        membership = await self.membership_repo.get_by_user_and_organization(
            requester_user_id, organization_id
        )
        if not membership or not has_permission(membership.role, "organization.update"):
            raise InsufficientPermissionError("organization.update")

        organization = await self.organization_repo.get_by_id(organization_id)
        if not organization:
            raise OrganizationNotFoundError(str(organization_id))

        organization.update(
            name=name, nif=nif, address=address, email=email, phone=phone
        )

        return await self.organization_repo.update(organization)
