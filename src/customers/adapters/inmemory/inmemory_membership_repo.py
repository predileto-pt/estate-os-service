from uuid import UUID

from customers.application.ports.repositories.membership_repository import (
    MembershipRepository,
)
from customers.domain.models.membership import Membership


class InMemoryMembershipRepository(MembershipRepository):
    def __init__(self) -> None:
        self._memberships: dict[UUID, Membership] = {}

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

    async def save(self, membership: Membership) -> Membership:
        self._memberships[membership.id] = membership
        return membership

    async def update(self, membership: Membership) -> Membership:
        self._memberships[membership.id] = membership
        return membership

    async def delete(self, membership_id: UUID) -> None:
        self._memberships.pop(membership_id, None)
