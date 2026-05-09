from __future__ import annotations

from dataclasses import dataclass


GOOGLE_MAPS_PLACE_URL = "https://www.google.com/maps/place/?q=place_id:{place_id}"

TOP_PLACES_LIMIT = 5


@dataclass(frozen=True)
class NearbyPlace:
    """A place near a property — a school, supermarket, bus stop, etc.

    Provider-agnostic value object: what Google Places (and any future
    POI provider) returns after normalization. Consumed by the
    `proximity_ranker` and the POI auto-discovery workflow.
    """

    name: str
    distance_meters: float
    latitude: float
    longitude: float
    place_id: str | None = None
    google_maps_url: str | None = None
