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

    `vicinity` is a short address string (e.g. "Rua Augusta 1, Lisboa")
    when the provider returns one — used by the locality sanitizer to
    drop POIs that fall outside the property's municipality / city
    without paying the Place Details cost.
    """

    name: str
    distance_meters: float
    latitude: float
    longitude: float
    place_id: str | None = None
    google_maps_url: str | None = None
    vicinity: str | None = None


@dataclass(frozen=True)
class PlaceDetails:
    """Rich metadata for a place — fetched from `PlacesService.get_place_details`.

    Phase 2 of the enrichment workflow consumes this to populate the
    `address`, `image_urls`, `reviews` columns on `PropertyPoi`. See spec
    `.claude/specs/active/2026-05-poi-rich-metadata.md`.

    Provider-agnostic. Google's `formatted_address` becomes `address`;
    photo references are resolved to CDN URLs by the adapter; reviews
    are pre-trimmed (≤5, only the fields we render).
    """

    place_id: str
    address: str | None
    image_urls: list[str]  # already resolved (CDN), at most 5
    reviews: list[dict] | None  # raw Google review objects, at most 5; None on failure or blacklist
