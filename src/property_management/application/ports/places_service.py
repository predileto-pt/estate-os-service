from __future__ import annotations

from abc import ABC, abstractmethod

from property_management.domain.models.property_amenity import NearbyPlace


class PlacesService(ABC):
    @abstractmethod
    async def find_nearby(
        self,
        latitude: float,
        longitude: float,
        place_type: str,
        radius_meters: int = 5000,
        keyword: str | None = None,
    ) -> list[NearbyPlace]: ...
