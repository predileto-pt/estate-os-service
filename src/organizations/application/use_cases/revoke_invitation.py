from uuid import UUID

import structlog

from organizations.application.ports.repositories.invitation_repository import (
    InvitationRepository,
)
from organizations.application.ports.repositories.membership_repository import (
    MembershipRepository,
)
from organizations.application.ports.repositories.user_repository import UserRepository
from organizations.domain.exceptions import (
    InsufficientPermissionError,
    InvitationNotFoundError,
)
from organizations.domain.models.authorization import has_permission
from organizations.domain.models.invitation import Invitation, InvitationStatus

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
        requester_user_id: UUID,
        invitation_id: UUID,
    ) -> Invitation:
        invitation = await self.invitation_repo.get_by_id(invitation_id)
        if not invitation:
            raise InvitationNotFoundError(str(invitation_id))

        membership = await self.membership_repo.get_by_user_and_organization(
            requester_user_id, invitation.organization_id
        )
        if not membership or not has_permission(membership.role, "member.invite"):
            raise InsufficientPermissionError("member.invite")

        invitation.status = InvitationStatus.REVOKED
        updated = await self.invitation_repo.update(invitation)

        log.info("invitation_revoked", invitation_id=str(invitation_id))
        return updated
