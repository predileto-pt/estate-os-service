from uuid import UUID

from supabase import AsyncClient

from customers.application.ports.repositories.invitation_repository import (
    InvitationRepository,
)
from customers.domain.models.invitation import Invitation, InvitationStatus
from customers.domain.models.membership import MembershipRole


class SupabaseInvitationRepository(InvitationRepository):
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    def _to_domain(self, row: dict) -> Invitation:
        return Invitation(
            id=UUID(row["id"]),
            organization_id=UUID(row["organization_id"]),
            email=row["email"],
            role=MembershipRole(row["role"]),
            invited_by=UUID(row["invited_by"]),
            token=row["token"],
            status=InvitationStatus(row["status"]),
            expires_at=row["expires_at"],
            created_at=row["created_at"],
        )

    def _to_row(self, invitation: Invitation) -> dict:
        return {
            "id": str(invitation.id),
            "organization_id": str(invitation.organization_id),
            "email": invitation.email,
            "role": invitation.role.value,
            "invited_by": str(invitation.invited_by),
            "token": invitation.token,
            "status": invitation.status.value,
            "expires_at": invitation.expires_at.isoformat(),
        }

    async def get_by_id(self, invitation_id: UUID) -> Invitation | None:
        result = (
            await self._client.table("invitations")
            .select("*")
            .eq("id", str(invitation_id))
            .execute()
        )
        if not result.data:
            return None
        return self._to_domain(result.data[0])

    async def get_pending_by_email(self, email: str) -> Invitation | None:
        result = (
            await self._client.table("invitations")
            .select("*")
            .eq("email", email)
            .eq("status", "pending")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        return self._to_domain(result.data[0])

    async def get_pending_by_email_and_organization(
        self, email: str, organization_id: UUID
    ) -> Invitation | None:
        result = (
            await self._client.table("invitations")
            .select("*")
            .eq("email", email)
            .eq("organization_id", str(organization_id))
            .eq("status", "pending")
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        return self._to_domain(result.data[0])

    async def list_by_organization(self, organization_id: UUID) -> list[Invitation]:
        result = (
            await self._client.table("invitations")
            .select("*")
            .eq("organization_id", str(organization_id))
            .execute()
        )
        return [self._to_domain(row) for row in result.data]

    async def save(self, invitation: Invitation) -> Invitation:
        result = await self._client.table("invitations").insert(self._to_row(invitation)).execute()
        return self._to_domain(result.data[0])

    async def update(self, invitation: Invitation) -> Invitation:
        row = {"status": invitation.status.value}
        result = (
            await self._client.table("invitations")
            .update(row)
            .eq("id", str(invitation.id))
            .execute()
        )
        return self._to_domain(result.data[0])
