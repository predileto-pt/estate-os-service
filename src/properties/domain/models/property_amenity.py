from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


class AmenityCategory(str, enum.Enum):
    HOSPITAL = "hospital"
    BANK = "bank"
    GROCERY = "grocery"
    SCHOOL = "school"
    LAUNDRY = "laundry"
    COFFEE_SHOP = "coffee_shop"
    PHARMACY = "pharmacy"
    GYM = "gym"
    RESTAURANT = "restaurant"


GOOGLE_MAPS_PLACE_URL = "https://www.google.com/maps/place/?q=place_id:{place_id}"


TOP_PLACES_LIMIT = 5


@dataclass(frozen=True)
class NearbyPlace:
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


@dataclass
class PropertyAmenity:
    id: UUID
    property_id: UUID
    category: AmenityCategory
    nearest_name: str
    nearest_distance_meters: float
    nearest_latitude: float
    nearest_longitude: float
    total_count: int
    created_at: datetime
    updated_at: datetime
    nearest_place_id: str | None = None
    nearest_google_maps_url: str | None = None
    top_places: list[NearbyPlace] = field(default_factory=list)
