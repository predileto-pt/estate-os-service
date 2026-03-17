from abc import ABC, abstractmethod
from uuid import UUID

from customer_management.domain.models.membership import Membership


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
    async def save(self, membership: Membership) -> Membership: ...

    @abstractmethod
    async def update(self, membership: Membership) -> Membership: ...

    @abstractmethod
    async def delete(self, membership_id: UUID) -> None: ...
