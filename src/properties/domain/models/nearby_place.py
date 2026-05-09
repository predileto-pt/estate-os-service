from __future__ import annotations

from dataclasses import dataclass


GOOGLE_MAPS_PLACE_URL = "https://www.google.com/maps/place/?q=place_id:{place_id}"

TOP_PLACES_LIMIT = 5


@dataclass(frozen=True)
class NearbyPlace:
    """A place near a property — a school, supermarket, bus stop, etc.

    Provider-agnostic value object: what Google Places, Overpass, and any
    future POI provider all return after normalization. Used by both the
    legacy `PropertyAmenity` summary surface and the newer `PropertyPoi`
    catalog. Lives in a neutral module so neither side imports the other's
    domain types.
    """

    name: str
    distance_meters: float
    latitude: float
    longitude: float
    place_id: str | None = None
    google_maps_url: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "distance_meters": self.distance_meters,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "place_id": self.place_id,
            "google_maps_url": self.google_maps_url,
        }

    @staticmethod
    def from_dict(data: dict) -> NearbyPlace:
        return NearbyPlace(
            name=data["name"],
            distance_meters=data["distance_meters"],
            latitude=data["latitude"],
            longitude=data["longitude"],
            place_id=data.get("place_id"),
            google_maps_url=data.get("google_maps_url"),
        )
