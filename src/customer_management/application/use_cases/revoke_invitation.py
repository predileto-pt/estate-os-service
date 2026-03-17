from uuid import UUID

import structlog

from customer_management.application.ports.repositories.invitation_repository import (
    InvitationRepository,
)
from customer_management.application.ports.repositories.membership_repository import (
    MembershipRepository,
)
from customer_management.application.ports.repositories.user_repository import UserRepository
from customer_management.domain.exceptions import (
    InsufficientPermissionError,
    InvitationNotFoundError,
    UserNotFoundError,
)
from customer_management.domain.models.authorization import has_permission
from customer_management.domain.models.invitation import Invitation, InvitationStatus

log = structlog.get_logger()


class RevokeInvitation:
    def __init__(
        self,
        invitation_repo: InvitationRepository,
        membership_repo: MembershipRepository,
        user_repo: UserRepository,
    ) -> None:
        self.invitation_repo = invitation_repo
        self.membership_repo = membership_repo
        self.user_repo = user_repo

    async def execute(
        self,
        *,
        supabase_user_id: str,
        invitation_id: UUID,
    ) -> Invitation:
        user = await self.user_repo.get_by_supabase_id(supabase_user_id)
        if not user:
            raise UserNotFoundError(supabase_user_id)

        invitation = await self.invitation_repo.get_by_id(invitation_id)
        if not invitation:
            raise InvitationNotFoundError(str(invitation_id))

        membership = await self.membership_repo.get_by_user_and_organization(
            user.id, invitation.organization_id
        )
        if not membership or not has_permission(membership.role, "member.invite"):
            raise InsufficientPermissionError("member.invite")

        invitation.status = InvitationStatus.REVOKED
        updated = await self.invitation_repo.update(invitation)

        log.info("invitation_revoked", invitation_id=str(invitation_id))
        return updated
