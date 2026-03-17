import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import structlog

from customer_management.application.ports.event_bus import EventBus
from customer_management.application.ports.repositories.invitation_repository import (
    InvitationRepository,
)
from customer_management.application.ports.repositories.membership_repository import (
    MembershipRepository,
)
from customer_management.application.ports.repositories.user_repository import UserRepository
from customer_management.domain.events import MemberInvited
from customer_management.domain.exceptions import (
    InsufficientPermissionError,
    MembershipAlreadyExistsError,
    UserNotFoundError,
)
from customer_management.domain.models.authorization import has_permission
from customer_management.domain.models.invitation import Invitation, InvitationStatus
from customer_management.domain.models.membership import MembershipRole

log = structlog.get_logger()

INVITATION_EXPIRY_DAYS = 7


class InviteMember:
    def __init__(
        self,
        invitation_repo: InvitationRepository,
        membership_repo: MembershipRepository,
        user_repo: UserRepository,
        event_bus: EventBus,
    ) -> None:
        self.invitation_repo = invitation_repo
        self.membership_repo = membership_repo
        self.user_repo = user_repo
        self.event_bus = event_bus

    async def execute(
        self,
        *,
        supabase_user_id: str,
        organization_id: UUID,
        email: str,
        role: MembershipRole,
    ) -> Invitation:
        inviter = await self.user_repo.get_by_supabase_id(supabase_user_id)
        if not inviter:
            raise UserNotFoundError(supabase_user_id)

        membership = await self.membership_repo.get_by_user_and_organization(
            inviter.id, organization_id
        )
        if not membership or not has_permission(membership.role, "member.invite"):
            raise InsufficientPermissionError("member.invite")

        # Check if the user is already a member
        existing_user = await self.user_repo.get_by_email(email)
        if existing_user:
            existing_membership = await self.membership_repo.get_by_user_and_organization(
                existing_user.id, organization_id
            )
            if existing_membership:
                raise MembershipAlreadyExistsError(email)

        now = datetime.now(timezone.utc)
        invitation = Invitation(
            id=uuid4(),
            organization_id=organization_id,
            email=email,
            role=role,
            invited_by=inviter.id,
            token=secrets.token_urlsafe(32),
            status=InvitationStatus.PENDING,
            expires_at=now + timedelta(days=INVITATION_EXPIRY_DAYS),
            created_at=now,
        )
        invitation = await self.invitation_repo.save(invitation)

        await self.event_bus.publish(
            MemberInvited(
                invitation_id=invitation.id,
                organization_id=organization_id,
                email=email,
                role=role.value,
            )
        )

        log.info(
            "member_invited",
            invitation_id=str(invitation.id),
            email=email,
            organization_id=str(organization_id),
        )
        return invitation
