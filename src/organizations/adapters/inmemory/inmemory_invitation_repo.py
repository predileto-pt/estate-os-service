from uuid import UUID

from customers.application.ports.repositories.invitation_repository import (
    InvitationRepository,
)
from customers.domain.models.invitation import Invitation, InvitationStatus


class InMemoryInvitationRepository(InvitationRepository):
    def __init__(self) -> None:
        self._invitations: dict[UUID, Invitation] = {}

    async def get_by_id(self, invitation_id: UUID) -> Invitation | None:
        return self._invitations.get(invitation_id)

    async def get_pending_by_email(self, email: str) -> Invitation | None:
        for inv in self._invitations.values():
            if inv.email == email and inv.status == InvitationStatus.PENDING:
                return inv
        return None

    async def get_pending_by_email_and_organization(
        self, email: str, organization_id: UUID
    ) -> Invitation | None:
        for inv in self._invitations.values():
            if (
                inv.email == email
                and inv.organization_id == organization_id
                and inv.status == InvitationStatus.PENDING
            ):
                return inv
        return None

    async def list_by_organization(self, organization_id: UUID) -> list[Invitation]:
        return [inv for inv in self._invitations.values() if inv.organization_id == organization_id]

    async def save(self, invitation: Invitation) -> Invitation:
        self._invitations[invitation.id] = invitation
        return invitation

    async def update(self, invitation: Invitation) -> Invitation:
        self._invitations[invitation.id] = invitation
        return invitation
