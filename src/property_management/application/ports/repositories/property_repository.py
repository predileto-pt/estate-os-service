from abc import ABC, abstractmethod
from uuid import UUID

from property_management.domain.models.property import Property
from property_management.domain.models.property_owner import PropertyOwner


class PropertyRepository(ABC):
    @abstractmethod
    async def get_by_id(self, property_id: UUID) -> Property | None: ...

    @abstractmethod
    async def list_by_organization(self, organization_id: UUID) -> list[Property]: ...

    @abstractmethod
    async def save(self, prop: Property) -> Property: ...

    @abstractmethod
    async def save_owner(self, prop: Property, owner: PropertyOwner) -> Property: ...
