from __future__ import annotations

from property_management.domain.models.property_amenity import (
    AmenityCategory,
    NearbyPlace,
)

KNOWN_BRANDS: dict[AmenityCategory, list[str]] = {
    AmenityCategory.BANK: [
        "Millennium",
        "BCP",
        "CGD",
        "Caixa Geral",
        "Santander",
        "BPI",
        "Novo Banco",
    ],
    AmenityCategory.GROCERY: [
        "Continente",
        "Lidl",
        "Pingo Doce",
        "Intermarché",
        "Mercadona",
    ],
}

KNOWN_BRAND_WEIGHT = 1.5
UNKNOWN_BRAND_WEIGHT = 1.0


def _is_known_brand(name: str, category: AmenityCategory) -> bool:
    brand_keywords = KNOWN_BRANDS.get(category)
    if not brand_keywords:
        return False
    name_lower = name.lower()
    return any(keyword.lower() in name_lower for keyword in brand_keywords)


def _score_place(place: NearbyPlace, category: AmenityCategory) -> float:
    weight = KNOWN_BRAND_WEIGHT if _is_known_brand(place.name, category) else UNKNOWN_BRAND_WEIGHT
    return weight / (1 + place.distance_meters)


def rank_places(places: list[NearbyPlace], category: AmenityCategory) -> NearbyPlace:
    """Return the best place for a category using brand-weighted scoring.

    For categories with known brands (banks, groceries), a known brand gets
    a 1.5x weight boost. For other categories, falls back to nearest by distance.
    """
    if category not in KNOWN_BRANDS:
        return min(places, key=lambda p: p.distance_meters)
    return max(places, key=lambda p: _score_place(p, category))


def rank_top_places(
    places: list[NearbyPlace],
    category: AmenityCategory,
    limit: int = 5,
) -> list[NearbyPlace]:
    """Return the top N places for a category, ranked by brand-weighted score."""
    if category not in KNOWN_BRANDS:
        return sorted(places, key=lambda p: p.distance_meters)[:limit]
    return sorted(places, key=lambda p: _score_place(p, category), reverse=True)[:limit]
