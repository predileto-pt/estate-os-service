from __future__ import annotations

from uuid import UUID

from properties.application.ports.repositories.property_amenity_repository import (
    PropertyAmenityRepository,
)
from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.exceptions import PropertyNotFoundError
from properties.domain.models.property_amenity import PropertyAmenity


class GetPropertyAmenities:
    def __init__(
        self,
        property_repo: PropertyRepository,
        amenity_repo: PropertyAmenityRepository,
    ) -> None:
        self.property_repo = property_repo
        self.amenity_repo = amenity_repo

    async def execute(self, *, property_id: str) -> list[PropertyAmenity]:
        prop = await self.property_repo.get_by_id(UUID(property_id))
        if not prop:
            raise PropertyNotFoundError(property_id)

        return await self.amenity_repo.get_by_property_id(prop.id)
