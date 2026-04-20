from uuid import UUID

from organizations.application.ports.repositories.membership_repository import (
    MembershipRepository,
    MembershipWithOrgName,
)
from organizations.application.ports.repositories.organization_repository import (
    OrganizationRepository,
)
from organizations.domain.models.membership import Membership


class InMemoryMembershipRepository(MembershipRepository):
    def __init__(
        self,
        organization_repo: OrganizationRepository | None = None,
    ) -> None:
        self._memberships: dict[UUID, Membership] = {}
        # Optional — only needed by `list_by_user_id_with_org_names` to
        # resolve organization names. Tests that don't need that method
        # can construct without it.
        self._organization_repo = organization_repo

    async def get_by_id(self, membership_id: UUID) -> Membership | None:
        return self._memberships.get(membership_id)

    async def get_by_user_and_organization(
        self, user_id: UUID, organization_id: UUID
    ) -> Membership | None:
        for m in self._memberships.values():
            if m.user_id == user_id and m.organization_id == organization_id:
                return m
        return None

    async def list_by_organization(self, organization_id: UUID) -> list[Membership]:
        return [m for m in self._memberships.values() if m.organization_id == organization_id]

    async def list_by_user(self, user_id: UUID) -> list[Membership]:
        return [m for m in self._memberships.values() if m.user_id == user_id]

    async def list_by_user_id_with_org_names(self, user_id: UUID) -> list[MembershipWithOrgName]:
        out: list[MembershipWithOrgName] = []
        for m in self._memberships.values():
            if m.user_id != user_id:
                continue
            org_name: str | None = None
            if self._organization_repo is not None:
                org = await self._organization_repo.get_by_id(m.organization_id)
                org_name = org.name if org else None
            out.append(
                MembershipWithOrgName(
                    id=m.id,
                    user_id=m.user_id,
                    organization_id=m.organization_id,
                    role=m.role,
                    organization_name=org_name,
                    created_at=m.created_at,
                    updated_at=m.updated_at,
                )
            )
        return out

    async def save(self, membership: Membership) -> Membership:
        self._memberships[membership.id] = membership
        return membership

    async def update(self, membership: Membership) -> Membership:
        self._memberships[membership.id] = membership
        return membership

    async def delete(self, membership_id: UUID) -> None:
        self._memberships.pop(membership_id, None)
