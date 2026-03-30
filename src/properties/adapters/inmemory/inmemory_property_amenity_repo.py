from __future__ import annotations

from uuid import UUID

from properties.application.ports.repositories.property_amenity_repository import (
    PropertyAmenityRepository,
)
from properties.domain.models.property_amenity import PropertyAmenity


class InMemoryPropertyAmenityRepository(PropertyAmenityRepository):
    def __init__(self) -> None:
        self._amenities: list[PropertyAmenity] = []

    async def save_batch(self, amenities: list[PropertyAmenity]) -> list[PropertyAmenity]:
        self._amenities.extend(amenities)
        return amenities

    async def get_by_property_id(self, property_id: UUID) -> list[PropertyAmenity]:
        return [a for a in self._amenities if a.property_id == property_id]

    async def delete_by_property_id(self, property_id: UUID) -> None:
        self._amenities = [a for a in self._amenities if a.property_id != property_id]
