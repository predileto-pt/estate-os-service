from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from properties.domain.models.nearby_place import NearbyPlace


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
