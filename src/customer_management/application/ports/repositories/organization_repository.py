from abc import ABC, abstractmethod
from uuid import UUID

from customer_management.domain.models.organization import Organization


class OrganizationRepository(ABC):
    @abstractmethod
    async def get_by_id(self, organization_id: UUID) -> Organization | None: ...

    @abstractmethod
    async def save(self, organization: Organization) -> Organization: ...

    @abstractmethod
    async def update(self, organization: Organization) -> Organization: ...
