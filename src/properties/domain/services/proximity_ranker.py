"""Proximity-weighted ranking of nearby places.

Category-agnostic. The caller passes the list of known brand keywords
for the category they're ranking; this module doesn't know whether
the category came from `AmenityCategory` (legacy) or `PoiCategory`
(new). Both `AmenityCategory.BANK.value == "bank"` and
`PoiCategory.BANK.value == "bank"`, so the brand-lookup table is
keyed by the enum's string value.
"""

from __future__ import annotations

from properties.domain.models.nearby_place import NearbyPlace


# Per-category known-brand keywords. Used to give a small score boost
# to recognized chains (e.g. "Pingo Doce" supermarket) over generic
# nearby results. Keyed by the enum value string so the same lookup
# works for AmenityCategory and PoiCategory.
KNOWN_BRANDS_BY_CATEGORY: dict[str, list[str]] = {
    "bank": [
        "Millennium",
        "BCP",
        "CGD",
        "Caixa Geral",
        "Santander",
        "BPI",
        "Novo Banco",
    ],
    "grocery": [
        "Continente",
        "Lidl",
        "Pingo Doce",
        "Intermarché",
        "Mercadona",
    ],
}


KNOWN_BRAND_WEIGHT = 1.5
UNKNOWN_BRAND_WEIGHT = 1.0


def _is_known_brand(name: str, brand_keywords: list[str]) -> bool:
    if not brand_keywords:
        return False
    name_lower = name.lower()
    return any(keyword.lower() in name_lower for keyword in brand_keywords)


def _score_place(place: NearbyPlace, brand_keywords: list[str]) -> float:
    weight = (
        KNOWN_BRAND_WEIGHT if _is_known_brand(place.name, brand_keywords) else UNKNOWN_BRAND_WEIGHT
    )
    return weight / (1 + place.distance_meters)


def rank_places(places: list[NearbyPlace], *, known_brands: list[str] | None = None) -> NearbyPlace:
    """Return the best place using brand-weighted scoring.

    When `known_brands` is None or empty, falls back to nearest-by-distance.
    Otherwise scores by `weight / (1 + distance_meters)` where weight is
    1.5 for recognized brands, 1.0 otherwise.
    """
    if not known_brands:
        return min(places, key=lambda p: p.distance_meters)
    return max(places, key=lambda p: _score_place(p, known_brands))


def rank_top_places(
    places: list[NearbyPlace],
    *,
    known_brands: list[str] | None = None,
    limit: int = 5,
) -> list[NearbyPlace]:
    """Return the top N places ranked by brand-weighted score (or
    nearest-distance when no brand list is provided).
    """
    if not known_brands:
        return sorted(places, key=lambda p: p.distance_meters)[:limit]
    return sorted(places, key=lambda p: _score_place(p, known_brands), reverse=True)[:limit]
