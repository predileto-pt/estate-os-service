from uuid import UUID

import structlog

from customers.application.ports.repositories.membership_repository import (
    MembershipRepository,
)
from customers.application.ports.repositories.user_repository import UserRepository
from customers.domain.exceptions import (
    InsufficientPermissionError,
    LastOwnerError,
    MembershipNotFoundError,
    UserNotFoundError,
)
from customers.domain.models.authorization import has_permission
from customers.domain.models.membership import MembershipRole

log = structlog.get_logger()


class RemoveMember:
    def __init__(
        self,
        membership_repo: MembershipRepository,
        user_repo: UserRepository,
    ) -> None:
        self.membership_repo = membership_repo
        self.user_repo = user_repo

    async def execute(
        self,
        *,
        supabase_user_id: str,
        membership_id: UUID,
    ) -> None:
        requester = await self.user_repo.get_by_supabase_id(supabase_user_id)
        if not requester:
            raise UserNotFoundError(supabase_user_id)

        target = await self.membership_repo.get_by_id(membership_id)
        if not target:
            raise MembershipNotFoundError(str(membership_id))

        requester_membership = await self.membership_repo.get_by_user_and_organization(
            requester.id, target.organization_id
        )
        if not requester_membership or not has_permission(
            requester_membership.role, "member.remove"
        ):
            raise InsufficientPermissionError("member.remove")

        # Prevent removing the last owner
        if target.role == MembershipRole.OWNER:
            members = await self.membership_repo.list_by_organization(target.organization_id)
            owner_count = sum(1 for m in members if m.role == MembershipRole.OWNER)
            if owner_count <= 1:
                raise LastOwnerError()

        await self.membership_repo.delete(target.id)

        log.info(
            "member_removed",
            membership_id=str(target.id),
            user_id=str(target.user_id),
        )
