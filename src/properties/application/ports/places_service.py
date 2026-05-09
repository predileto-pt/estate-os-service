from __future__ import annotations

from abc import ABC, abstractmethod

from properties.domain.models.nearby_place import NearbyPlace, PlaceDetails


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

    @abstractmethod
    async def get_place_details(
        self,
        place_id: str,
        *,
        include_reviews: bool = True,
    ) -> PlaceDetails | None:
        """Fetch rich metadata for a place. Returns None on any failure
        (HTTP error, missing place_id, API quota exhausted, malformed
        response). Caller treats `None` as 'no metadata available'.

        `include_reviews=False` skips the reviews payload server-side
        (saves cost on Google's atmosphere SKU for blacklisted
        categories per the POI rich-metadata spec).
        """
        ...
