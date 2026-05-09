from __future__ import annotations

from properties.application.ports.places_service import PlacesService
from properties.domain.models.nearby_place import NearbyPlace


class InMemoryPlacesService(PlacesService):
    def __init__(self, results: dict[str, list[NearbyPlace]] | None = None) -> None:
        self._results: dict[str, list[NearbyPlace]] = results or {}

    def set_results(
        self, place_type: str, places: list[NearbyPlace], keyword: str | None = None
    ) -> None:
        key = f"{place_type}:{keyword}" if keyword else place_type
        self._results[key] = places

    async def find_nearby(
        self,
        latitude: float,
        longitude: float,
        place_type: str,
        radius_meters: int = 5000,
        keyword: str | None = None,
    ) -> list[NearbyPlace]:
        key = f"{place_type}:{keyword}" if keyword else place_type
        return self._results.get(key, [])
