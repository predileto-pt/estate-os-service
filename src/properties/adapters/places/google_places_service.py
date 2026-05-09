from __future__ import annotations

import math

import httpx
import structlog

from properties.application.ports.places_service import PlacesService
from properties.domain.models.nearby_place import GOOGLE_MAPS_PLACE_URL, NearbyPlace

log = structlog.get_logger()

NEARBY_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in meters between two points using haversine formula."""
    r = 6_371_000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class GooglePlacesService(PlacesService):
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def find_nearby(
        self,
        latitude: float,
        longitude: float,
        place_type: str,
        radius_meters: int = 5000,
        keyword: str | None = None,
    ) -> list[NearbyPlace]:
        params: dict[str, str | int] = {
            "location": f"{latitude},{longitude}",
            "radius": radius_meters,
            "type": place_type,
            "key": self._api_key,
        }
        if keyword:
            params["keyword"] = keyword

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(NEARBY_SEARCH_URL, params=params)
                response.raise_for_status()
                data = response.json()
        except Exception:
            log.exception(
                "google_places.request_failed",
                place_type=place_type,
                keyword=keyword,
            )
            return []

        status = data.get("status")
        if status not in ("OK", "ZERO_RESULTS"):
            log.warning(
                "google_places.api_error",
                status=status,
                error_message=data.get("error_message"),
            )
            return []

        results = data.get("results", [])
        places: list[NearbyPlace] = []

        for result in results:
            location = result.get("geometry", {}).get("location", {})
            place_lat = location.get("lat")
            place_lng = location.get("lng")
            name = result.get("name", "")
            place_id = result.get("place_id")

            if place_lat is None or place_lng is None or not name:
                continue

            distance = _haversine_distance(latitude, longitude, place_lat, place_lng)
            google_maps_url = GOOGLE_MAPS_PLACE_URL.format(place_id=place_id) if place_id else None
            places.append(
                NearbyPlace(
                    name=name,
                    distance_meters=round(distance, 1),
                    latitude=place_lat,
                    longitude=place_lng,
                    place_id=place_id,
                    google_maps_url=google_maps_url,
                )
            )

        log.info(
            "google_places.search_completed",
            place_type=place_type,
            keyword=keyword,
            results_count=len(places),
        )
        return places
