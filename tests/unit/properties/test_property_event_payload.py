"""Unit tests for `build_property_snapshot`'s POI sub-payload shape.

Defends against an accidental refactor that strips the rich POI
fields (`address`, `image_urls`, `reviews`) from the snapshot.
ADR-014 §13 made these load-bearing for the listings search
matched-POI response — without them, the projection's `ListingPoi`
has nothing to populate the rich fields with and the matched-POI
response silently downgrades to the same 3 fields v1 already had.

This is a properties-side test pinning a contract the listings
context depends on. The closed-vocabulary `PoiCategory` value-set
alignment is pinned separately in
`tests/unit/listings/test_poi_category_contract.py`.

Spec: `2026-05-listing-search-structured-extraction` §13.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from properties.application.events.property_event import build_property_snapshot
from properties.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)
from properties.domain.models.property_poi import PoiCategory, PropertyPoi


def _prop() -> Property:
    now = datetime.now(timezone.utc)
    return Property(
        id=uuid4(),
        organization_id=uuid4(),
        title="Test property",
        address="Rua das Flores, 12, Cascais",
        listing_type=ListingType.SALE,
        typology=Typology.APARTMENT,
        status=PropertyStatus.ACTIVE,
        description=None,
        characteristics=None,
        latitude=None,
        longitude=None,
        created_at=now,
        updated_at=now,
    )


def _poi(
    *,
    name: str = "Escola Básica de Cascais",
    category: PoiCategory = PoiCategory.SCHOOL,
    distance: float = 480.0,
    address: str | None = "Rua das Flores 12",
    image_urls: list[str] | None = None,
    reviews: list[dict] | None = None,
) -> PropertyPoi:
    return PropertyPoi(
        id=uuid4(),
        property_id=uuid4(),
        category=category,
        name=name,
        distance_meters=distance,
        latitude=38.7,
        longitude=-9.4,
        address=address,
        image_urls=image_urls or [],
        reviews=reviews,
    )


class TestPoiSubPayloadShape:
    def test_lean_fields_preserved(self):
        """The original 3 fields (category, name, distance_meters)
        must still be in every POI dict — back-compat for any
        consumer that doesn't yet read the new keys."""
        payload = build_property_snapshot(_prop(), [_poi()])
        assert "pois" in payload
        assert len(payload["pois"]) == 1
        poi = payload["pois"][0]
        assert poi["category"] == "school"
        assert poi["name"] == "Escola Básica de Cascais"
        assert poi["distance_meters"] == 480.0

    def test_rich_fields_surface(self):
        """The three new fields (ADR-014 §13) must flow from
        PropertyPoi to the payload. Without this the listings
        projector has nothing to populate ListingPoi.address /
        image_urls / reviews with."""
        payload = build_property_snapshot(
            _prop(),
            [
                _poi(
                    address="Rua A, 12",
                    image_urls=["https://x/1.jpg", "https://x/2.jpg"],
                    reviews=[{"rating": 4, "text": "Great"}],
                )
            ],
        )
        poi = payload["pois"][0]
        assert poi["address"] == "Rua A, 12"
        assert poi["image_urls"] == ["https://x/1.jpg", "https://x/2.jpg"]
        assert poi["reviews"] == [{"rating": 4, "text": "Great"}]

    def test_null_rich_fields_round_trip_as_null(self):
        """PropertyPoi.address and reviews are nullable; empty
        image_urls is a list. The payload should preserve these
        without coercing to False-y values."""
        payload = build_property_snapshot(
            _prop(),
            [_poi(address=None, image_urls=[], reviews=None)],
        )
        poi = payload["pois"][0]
        assert poi["address"] is None
        assert poi["image_urls"] == []
        assert poi["reviews"] is None

    def test_image_urls_iterable_normalized_to_list(self):
        """The builder uses `list(poi.image_urls or [])` to defend
        against tuple/None inputs. Sanity-check that whatever the
        domain side has (currently list[str]) the payload is a
        list — listings JSONB serialization needs a list."""
        payload = build_property_snapshot(
            _prop(), [_poi(image_urls=["a.jpg", "b.jpg"])]
        )
        urls = payload["pois"][0]["image_urls"]
        assert isinstance(urls, list)
        assert urls == ["a.jpg", "b.jpg"]

    def test_pois_omitted_when_none(self):
        """No pois argument → no `pois` key in the payload. Existing
        contract (events that don't carry POIs)."""
        payload = build_property_snapshot(_prop())
        assert "pois" not in payload

    def test_pois_empty_list_renders_empty(self):
        """Explicit empty POI list → `"pois": []` (NOT absent).
        Authoritative "this property has no POIs nearby" signal."""
        payload = build_property_snapshot(_prop(), [])
        assert payload["pois"] == []
