from __future__ import annotations

from properties.application.ports.places_service import PlacesService
from properties.domain.models.nearby_place import NearbyPlace, PlaceDetails


class InMemoryPlacesService(PlacesService):
    def __init__(self, results: dict[str, list[NearbyPlace]] | None = None) -> None:
        self._results: dict[str, list[NearbyPlace]] = results or {}
        self._details: dict[str, PlaceDetails | None] = {}

    def set_results(
        self, place_type: str, places: list[NearbyPlace], keyword: str | None = None
    ) -> None:
        key = f"{place_type}:{keyword}" if keyword else place_type
        self._results[key] = places

    def set_place_details(self, place_id: str, details: PlaceDetails | None) -> None:
        """Seed a PlaceDetails response (or None to simulate failure) for
        a given place_id. Used by tests exercising Phase 2 of enrichment.
        """
        self._details[place_id] = details

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

    async def get_place_details(
        self,
        place_id: str,
        *,
        include_reviews: bool = True,
    ) -> PlaceDetails | None:
        details = self._details.get(place_id)
        if details is None:
            return None
        if not include_reviews:
            # Mirror the Google adapter's cost-aware behavior: when the
            # caller doesn't want reviews, don't surface them.
            return PlaceDetails(
                place_id=details.place_id,
                address=details.address,
                image_urls=list(details.image_urls),
                reviews=None,
            )
        return details
