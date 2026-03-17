from uuid import UUID

from property_management.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from property_management.domain.models.property import Property
from property_management.domain.models.property_owner import PropertyOwner


class InMemoryPropertyRepository(PropertyRepository):
    def __init__(self) -> None:
        self._properties: dict[UUID, Property] = {}

    async def get_by_id(self, property_id: UUID) -> Property | None:
        return self._properties.get(property_id)

    async def list_by_organization(self, organization_id: UUID) -> list[Property]:
        return [p for p in self._properties.values() if p.organization_id == organization_id]

    async def save(self, prop: Property) -> Property:
        self._properties[prop.id] = prop
        return prop

    async def save_owner(self, prop: Property, owner: PropertyOwner) -> Property:
        prop.add_owner(owner)
        self._properties[prop.id] = prop
        return prop
