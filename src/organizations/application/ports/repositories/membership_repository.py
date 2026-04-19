from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from organizations.domain.models.membership import Membership, MembershipRole


@dataclass(frozen=True)
class MembershipWithOrgName:
    """Projection used by `IdentityMiddleware` and `/auth/me`.

    Carries enough data to render a membership list in one request without
    N+1: the membership core + the denormalised `organization_name` from
    the JOINed `organizations` table. Not a domain aggregate — read-only
    projection.
    """

    id: UUID
    user_id: UUID
    organization_id: UUID
    role: MembershipRole
    organization_name: str | None
    created_at: datetime
    updated_at: datetime


class MembershipRepository(ABC):
    @abstractmethod
    async def get_by_id(self, membership_id: UUID) -> Membership | None: ...

    @abstractmethod
    async def get_by_user_and_organization(
        self, user_id: UUID, organization_id: UUID
    ) -> Membership | None: ...

    @abstractmethod
    async def list_by_organization(self, organization_id: UUID) -> list[Membership]: ...

    @abstractmethod
    async def list_by_user(self, user_id: UUID) -> list[Membership]: ...

    @abstractmethod
    async def list_by_user_id_with_org_names(
        self, user_id: UUID
    ) -> list[MembershipWithOrgName]: ...

    @abstractmethod
    async def save(self, membership: Membership) -> Membership: ...

    @abstractmethod
    async def update(self, membership: Membership) -> Membership: ...

    @abstractmethod
    async def delete(self, membership_id: UUID) -> None: ...
