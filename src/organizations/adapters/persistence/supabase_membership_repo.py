from uuid import UUID

from supabase import AsyncClient

from organizations.application.ports.repositories.membership_repository import (
    MembershipRepository,
    MembershipWithOrgName,
)
from organizations.domain.models.membership import Membership, MembershipRole


class SupabaseMembershipRepository(MembershipRepository):
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    def _to_domain(self, row: dict) -> Membership:
        return Membership(
            id=UUID(row["id"]),
            user_id=UUID(row["user_id"]),
            organization_id=UUID(row["organization_id"]),
            role=MembershipRole(row["role"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _to_row(self, membership: Membership) -> dict:
        return {
            "id": str(membership.id),
            "user_id": str(membership.user_id),
            "organization_id": str(membership.organization_id),
            "role": membership.role.value,
        }

    async def get_by_id(self, membership_id: UUID) -> Membership | None:
        result = (
            await self._client.table("memberships")
            .select("*")
            .eq("id", str(membership_id))
            .execute()
        )
        if not result.data:
            return None
        return self._to_domain(result.data[0])

    async def get_by_user_and_organization(
        self, user_id: UUID, organization_id: UUID
    ) -> Membership | None:
        result = (
            await self._client.table("memberships")
            .select("*")
            .eq("user_id", str(user_id))
            .eq("organization_id", str(organization_id))
            .execute()
        )
        if not result.data:
            return None
        return self._to_domain(result.data[0])

    async def list_by_organization(self, organization_id: UUID) -> list[Membership]:
        result = (
            await self._client.table("memberships")
            .select("*")
            .eq("organization_id", str(organization_id))
            .execute()
        )
        return [self._to_domain(row) for row in result.data]

    async def list_by_user(self, user_id: UUID) -> list[Membership]:
        result = (
            await self._client.table("memberships")
            .select("*")
            .eq("user_id", str(user_id))
            .execute()
        )
        return [self._to_domain(row) for row in result.data]

    async def list_by_user_id_with_org_names(self, user_id: UUID) -> list[MembershipWithOrgName]:
        # PostgREST embedded resource join: single round-trip.
        result = (
            await self._client.table("memberships")
            .select("*, organizations(name)")
            .eq("user_id", str(user_id))
            .execute()
        )
        out: list[MembershipWithOrgName] = []
        for row in result.data:
            org = row.get("organizations") or {}
            out.append(
                MembershipWithOrgName(
                    id=UUID(row["id"]),
                    user_id=UUID(row["user_id"]),
                    organization_id=UUID(row["organization_id"]),
                    role=MembershipRole(row["role"]),
                    organization_name=org.get("name") if isinstance(org, dict) else None,
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
            )
        return out

    async def save(self, membership: Membership) -> Membership:
        result = await self._client.table("memberships").insert(self._to_row(membership)).execute()
        return self._to_domain(result.data[0])

    async def update(self, membership: Membership) -> Membership:
        row = self._to_row(membership)
        result = (
            await self._client.table("memberships")
            .update(row)
            .eq("id", str(membership.id))
            .execute()
        )
        return self._to_domain(result.data[0])

    async def delete(self, membership_id: UUID) -> None:
        await self._client.table("memberships").delete().eq("id", str(membership_id)).execute()
