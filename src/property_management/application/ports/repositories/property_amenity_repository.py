from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from property_management.domain.models.property_amenity import PropertyAmenity


class PropertyAmenityRepository(ABC):
    @abstractmethod
    async def save_batch(self, amenities: list[PropertyAmenity]) -> list[PropertyAmenity]: ...

    @abstractmethod
    async def get_by_property_id(self, property_id: UUID) -> list[PropertyAmenity]: ...

    @abstractmethod
    async def delete_by_property_id(self, property_id: UUID) -> None: ...
