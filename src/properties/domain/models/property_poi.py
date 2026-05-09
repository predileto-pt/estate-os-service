from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


class PoiCategory(str, enum.Enum):
    HOSPITAL = "hospital"
    BANK = "bank"
    GROCERY = "grocery"
    SCHOOL = "school"
    PHARMACY = "pharmacy"
    GYM = "gym"
    RESTAURANT = "restaurant"
    COFFEE_SHOP = "coffee_shop"
    LAUNDRY = "laundry"
    GAS_STATION = "gas_station"
    PUBLIC_TRANSIT = "public_transit"
    KINDERGARTEN = "kindergarten"
    PARK = "park"
    POST_OFFICE = "post_office"
    LIBRARY = "library"
    SHOPPING_MALL = "shopping_mall"
    BAKERY = "bakery"
    POLICE_STATION = "police_station"
    # Auto services. Both share Google's `car_repair` place_type — the
    # discovery layer disambiguates with a per-category keyword
    # (PT: "pneus" / "oficina mecânica") so the same shop doesn't
    # appear in both buckets.
    TIRE_SHOP = "tire_shop"
    AUTO_SHOP = "auto_shop"


@dataclass
class PropertyPoi:
    """A point of interest near a property — a school, supermarket, bus
    stop, etc. Discovered automatically by the enrichment workflow or
    entered/edited manually by an agent.

    `metadata` is intentionally untyped: provider-specific extras (Google
    rating, OSM tags) and agent notes coexist without us pre-defining
    the keys.
    """

    id: UUID
    property_id: UUID
    category: PoiCategory
    name: str
    distance_meters: float
    latitude: float
    longitude: float
    place_type: str | None = None
    place_id: str | None = None
    metadata: dict = field(default_factory=dict)
    manually_edited: bool = False
    # Place-details fields (ADR / spec 2026-05-poi-rich-metadata).
    # Populated by Phase 2 of the enrichment workflow; nullable / empty
    # for manually-entered POIs that haven't been enriched.
    address: str | None = None
    image_urls: list[str] = field(default_factory=list)
    reviews: list[dict] | None = None
    created_at: datetime | None = None  # set by the adapter on insert
    updated_at: datetime | None = None
