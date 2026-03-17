from customer_management.application.ports.repositories.membership_repository import (
    MembershipRepository,
)
from customer_management.application.ports.repositories.organization_repository import (
    OrganizationRepository,
)
from customer_management.application.ports.repositories.user_repository import UserRepository
from customer_management.domain.exceptions import UserNotFoundError
from customer_management.domain.models.membership import Membership
from customer_management.domain.models.organization import Organization
from customer_management.domain.models.user import User


class GetUserProfile:
    def __init__(
        self,
        user_repo: UserRepository,
        organization_repo: OrganizationRepository,
        membership_repo: MembershipRepository,
    ) -> None:
        self.user_repo = user_repo
        self.organization_repo = organization_repo
        self.membership_repo = membership_repo

    async def execute(
        self, *, supabase_user_id: str
    ) -> tuple[User, Organization | None, Membership | None]:
        user = await self.user_repo.get_by_supabase_id(supabase_user_id)
        if not user:
            raise UserNotFoundError(supabase_user_id)

        organization = None
        membership = None

        if user.organization_id:
            organization = await self.organization_repo.get_by_id(user.organization_id)
            memberships = await self.membership_repo.list_by_user(user.id)
            if memberships:
                # Find membership for the user's organization
                for m in memberships:
                    if m.organization_id == user.organization_id:
                        membership = m
                        break

        return user, organization, membership
