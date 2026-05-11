"""msgpack codec for cached PropertyListing payloads + ParsedQuery.

Both Redis adapters delegate here so the typed ↔ primitive-dict
mapping is one cohesive piece of code rather than duplicated codec
pairs per port.

Round-trip contract: `from_listing(to_listing_dict(x)) == x` for any
PropertyListing produced by the projector — verified by the codec
round-trip test in `test_listing_codec.py`. Likewise for ParsedQuery.

UUIDs → str, datetimes → ISO, Decimals → str, enums → value. The
inverse reconstructs typed values so use cases always see domain
types (the search use case's
`rows.sort(key=lambda r: order[r.id])` depends on UUID keys, not
str keys).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from listings.application.ports.listings_page_cache import CachedPage
from listings.application.ports.search_result_cache import CachedSearchResult
from listings.domain.models import ListingType, PropertyStatus, Typology
from listings.domain.parsed_query import ParsedQuery
from listings.domain.poi_category import PoiCategory
from listings.domain.property_listing import (
    ListingImage,
    ListingPoi,
    ListingPrice,
    PropertyListing,
)


# ─── PropertyListing ↔ dict ───────────────────────────────────────────────


def _poi_to_dict(p: ListingPoi) -> dict[str, Any]:
    return {
        "category": p.category,
        "name": p.name,
        "distance_meters": p.distance_meters,
        "address": p.address,
        "image_urls": list(p.image_urls),
        "reviews": p.reviews,
    }


def _poi_from_dict(d: dict[str, Any]) -> ListingPoi:
    return ListingPoi(
        category=d["category"],
        name=d["name"],
        distance_meters=d["distance_meters"],
        address=d.get("address"),
        image_urls=list(d.get("image_urls") or []),
        reviews=d.get("reviews"),
    )


def _image_to_dict(i: ListingImage) -> dict[str, Any]:
    return {"id": str(i.id), "s3_key": i.s3_key, "display_order": i.display_order}


def _image_from_dict(d: dict[str, Any]) -> ListingImage:
    return ListingImage(
        id=UUID(d["id"]),
        s3_key=d["s3_key"],
        display_order=d["display_order"],
    )


def _price_to_dict(p: ListingPrice) -> dict[str, Any]:
    return {"amount": str(p.amount), "listing_type": p.listing_type.value}


def _price_from_dict(d: dict[str, Any]) -> ListingPrice:
    return ListingPrice(
        amount=Decimal(d["amount"]),
        listing_type=ListingType(d["listing_type"]),
    )


def _iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _datetime_or_none(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def to_listing_dict(listing: PropertyListing) -> dict[str, Any]:
    return {
        "id": str(listing.id),
        "organization_id": str(listing.organization_id),
        "title": listing.title,
        "status": listing.status.value,
        "listing_type": listing.listing_type.value,
        "typology": listing.typology.value,
        "parish": listing.parish,
        "municipality": listing.municipality,
        "district": listing.district,
        "location_enriched_at": _iso_or_none(listing.location_enriched_at),
        "location_enrichment_attempts": listing.location_enrichment_attempts,
        "num_of_bedrooms": listing.num_of_bedrooms,
        "num_of_bathrooms": listing.num_of_bathrooms,
        "area_in_m2": listing.area_in_m2,
        "has_pool": listing.has_pool,
        "has_garden": listing.has_garden,
        "has_elevator": listing.has_elevator,
        "min_price": str(listing.min_price) if listing.min_price is not None else None,
        "first_image_s3_key": listing.first_image_s3_key,
        "description": listing.description,
        "latitude": listing.latitude,
        "longitude": listing.longitude,
        "source_aggregate_version": listing.source_aggregate_version,
        "source_occurred_at": listing.source_occurred_at.isoformat(),
        "created_at": listing.created_at.isoformat(),
        "updated_at": listing.updated_at.isoformat(),
        "built_at": listing.built_at,
        "energy_rating": listing.energy_rating,
        "floor": listing.floor,
        "parking_spaces": listing.parking_spaces,
        "country": listing.country,
        "city": listing.city,
        "state": listing.state,
        "region": listing.region,
        "images": [_image_to_dict(i) for i in listing.images],
        "prices": [_price_to_dict(p) for p in listing.prices],
        "pois": [_poi_to_dict(p) for p in listing.pois],
        "embedding_text_hash": listing.embedding_text_hash,
        "canonical_text_version": listing.canonical_text_version,
        "embedding_model_version": listing.embedding_model_version,
        "embedded_at": _iso_or_none(listing.embedded_at),
        "embedding_status": listing.embedding_status,
    }


def from_listing_dict(d: dict[str, Any]) -> PropertyListing:
    return PropertyListing(
        id=UUID(d["id"]),
        organization_id=UUID(d["organization_id"]),
        title=d.get("title") or "Property",
        status=PropertyStatus(d["status"]),
        listing_type=ListingType(d["listing_type"]),
        typology=Typology(d["typology"]),
        parish=d.get("parish"),
        municipality=d.get("municipality"),
        district=d.get("district"),
        location_enriched_at=_datetime_or_none(d.get("location_enriched_at")),
        location_enrichment_attempts=d.get("location_enrichment_attempts", 0),
        num_of_bedrooms=d.get("num_of_bedrooms"),
        num_of_bathrooms=d.get("num_of_bathrooms"),
        area_in_m2=d.get("area_in_m2"),
        has_pool=d.get("has_pool"),
        has_garden=d.get("has_garden"),
        has_elevator=d.get("has_elevator"),
        min_price=Decimal(d["min_price"]) if d.get("min_price") is not None else None,
        first_image_s3_key=d.get("first_image_s3_key"),
        description=d.get("description"),
        latitude=d.get("latitude"),
        longitude=d.get("longitude"),
        source_aggregate_version=d["source_aggregate_version"],
        source_occurred_at=datetime.fromisoformat(d["source_occurred_at"]),
        created_at=datetime.fromisoformat(d["created_at"]),
        updated_at=datetime.fromisoformat(d["updated_at"]),
        built_at=d.get("built_at"),
        energy_rating=d.get("energy_rating"),
        floor=d.get("floor"),
        parking_spaces=d.get("parking_spaces"),
        country=d.get("country", "Portugal"),
        city=d.get("city"),
        state=d.get("state"),
        region=d.get("region"),
        images=[_image_from_dict(i) for i in d.get("images", [])],
        prices=[_price_from_dict(p) for p in d.get("prices", [])],
        pois=[_poi_from_dict(p) for p in d.get("pois", [])],
        embedding_text_hash=d.get("embedding_text_hash"),
        canonical_text_version=d.get("canonical_text_version"),
        embedding_model_version=d.get("embedding_model_version"),
        embedded_at=_datetime_or_none(d.get("embedded_at")),
        embedding_status=d.get("embedding_status", "PENDING"),
    )


# ─── CachedPage ↔ dict ────────────────────────────────────────────────────


def to_page_dict(page: CachedPage) -> dict[str, Any]:
    return {
        "items": [to_listing_dict(it) for it in page.items],
        "next_cursor": page.next_cursor,
    }


def from_page_dict(d: dict[str, Any]) -> CachedPage:
    return CachedPage(
        items=[from_listing_dict(it) for it in d.get("items", [])],
        next_cursor=d.get("next_cursor"),
    )


# ─── ParsedQuery ↔ dict ───────────────────────────────────────────────────


def _to_decimal_str(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _from_decimal_str(value: str | None) -> Decimal | None:
    return Decimal(value) if value is not None else None


def to_parsed_query_dict(parsed: ParsedQuery) -> dict[str, Any]:
    return {
        "free_text_remainder": parsed.free_text_remainder,
        "typology": parsed.typology.value if parsed.typology is not None else None,
        "min_bedrooms": parsed.min_bedrooms,
        "min_bathrooms": parsed.min_bathrooms,
        "min_area_m2": parsed.min_area_m2,
        "max_area_m2": parsed.max_area_m2,
        "min_price": _to_decimal_str(parsed.min_price),
        "max_price": _to_decimal_str(parsed.max_price),
        "has_pool": parsed.has_pool,
        "has_garden": parsed.has_garden,
        "has_elevator": parsed.has_elevator,
        "has_parking": parsed.has_parking,
        "nearby_pois": [c.value for c in parsed.nearby_pois],
    }


def from_parsed_query_dict(d: dict[str, Any]) -> ParsedQuery:
    typology_value = d.get("typology")
    return ParsedQuery(
        free_text_remainder=d.get("free_text_remainder", ""),
        typology=Typology(typology_value) if typology_value is not None else None,
        min_bedrooms=d.get("min_bedrooms"),
        min_bathrooms=d.get("min_bathrooms"),
        min_area_m2=d.get("min_area_m2"),
        max_area_m2=d.get("max_area_m2"),
        min_price=_from_decimal_str(d.get("min_price")),
        max_price=_from_decimal_str(d.get("max_price")),
        has_pool=d.get("has_pool"),
        has_garden=d.get("has_garden"),
        has_elevator=d.get("has_elevator"),
        has_parking=d.get("has_parking"),
        nearby_pois=tuple(PoiCategory(v) for v in d.get("nearby_pois", [])),
    )


# ─── CachedSearchResult ↔ dict ────────────────────────────────────────────


def to_search_result_dict(result: CachedSearchResult) -> dict[str, Any]:
    return {
        "parsed": to_parsed_query_dict(result.parsed),
        "ranked_ids": [str(i) for i in result.ranked_ids],
    }


def from_search_result_dict(d: dict[str, Any]) -> CachedSearchResult:
    return CachedSearchResult(
        parsed=from_parsed_query_dict(d["parsed"]),
        ranked_ids=[UUID(s) for s in d.get("ranked_ids", [])],
    )
