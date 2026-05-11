"""Codec round-trip tests — typed → dict → msgpack → dict → typed.

These cover both adapter ports (page cache + search-result cache)
because they share the codec. Tests prove:

- Round-trip preserves *typed* values (UUIDs from strings, datetimes
  from ISO, enums from values, Decimals from strings).
- Nested types (ListingPoi, ListingImage, ListingPrice) round-trip.
- ParsedQuery's `nearby_pois` tuple round-trips as a tuple of typed
  enums.
- The cache value survives a real msgpack pack/unpack — not just the
  pure dict round-trip.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import msgpack

from listings.adapters.cache.listing_codec import (
    from_listing_dict,
    from_page_dict,
    from_parsed_query_dict,
    from_search_result_dict,
    to_listing_dict,
    to_page_dict,
    to_parsed_query_dict,
    to_search_result_dict,
)
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


def _full_listing() -> PropertyListing:
    """Listing with every optional field populated — exercises the
    codec's typed-reconstruction paths exhaustively."""
    now = datetime(2026, 5, 11, 12, 0, 0, tzinfo=timezone.utc)
    return PropertyListing(
        id=uuid4(),
        organization_id=uuid4(),
        status=PropertyStatus.ACTIVE,
        listing_type=ListingType.SALE,
        typology=Typology.APARTMENT,
        parish="Misericórdia",
        municipality="Lisboa",
        district="Lisboa",
        location_enriched_at=now,
        location_enrichment_attempts=1,
        num_of_bedrooms=2,
        num_of_bathrooms=1,
        area_in_m2=85,
        has_pool=False,
        has_garden=True,
        has_elevator=True,
        min_price=Decimal("380000.00"),
        first_image_s3_key="properties/x/images/a.jpg",
        description="Apartamento no Chiado",
        latitude=38.71,
        longitude=-9.14,
        source_aggregate_version=3,
        source_occurred_at=now,
        created_at=now,
        updated_at=now,
        built_at=1920,
        energy_rating="B",
        floor=4,
        parking_spaces=1,
        country="Portugal",
        city="Lisboa",
        state=None,
        region=None,
        images=[
            ListingImage(id=uuid4(), s3_key="properties/x/images/a.jpg", display_order=0),
            ListingImage(id=uuid4(), s3_key="properties/x/images/b.jpg", display_order=1),
        ],
        prices=[ListingPrice(amount=Decimal("380000.00"), listing_type=ListingType.SALE)],
        pois=[
            ListingPoi(
                category=PoiCategory.HOSPITAL.value,
                name="Hospital São José",
                distance_meters=420.5,
                address="R. José António Serrano",
                image_urls=["https://x/1.jpg"],
                reviews=[{"rating": 4.2, "count": 1234}],
            ),
        ],
        embedding_text_hash="deadbeef",
        canonical_text_version="v3",
        embedding_model_version="text-embedding-3-small",
        embedded_at=now,
        embedding_status="EMBEDDED",
    )


def test_listing_roundtrip_preserves_types():
    original = _full_listing()
    restored = from_listing_dict(to_listing_dict(original))

    assert restored == original
    # Spot-check that types weren't silently downgraded to strings.
    assert isinstance(restored.id, type(original.id))
    assert isinstance(restored.status, PropertyStatus)
    assert isinstance(restored.min_price, Decimal)
    assert isinstance(restored.created_at, datetime)
    assert isinstance(restored.images[0].id, type(original.images[0].id))
    assert isinstance(restored.prices[0].listing_type, ListingType)


def test_listing_roundtrip_through_msgpack():
    original = _full_listing()
    packed = msgpack.packb(to_listing_dict(original), use_bin_type=True)
    unpacked = msgpack.unpackb(packed, raw=False)
    restored = from_listing_dict(unpacked)
    assert restored == original


def test_page_roundtrip_through_msgpack():
    page = CachedPage(items=[_full_listing(), _full_listing()], next_cursor="abc.token")
    packed = msgpack.packb(to_page_dict(page), use_bin_type=True)
    restored = from_page_dict(msgpack.unpackb(packed, raw=False))
    assert restored == page


def test_page_with_no_next_cursor():
    page = CachedPage(items=[], next_cursor=None)
    restored = from_page_dict(to_page_dict(page))
    assert restored == page


def test_parsed_query_roundtrip_through_msgpack():
    parsed = ParsedQuery(
        free_text_remainder="apartamento jeitoso perto da escola",
        typology=Typology.APARTMENT,
        min_bedrooms=2,
        min_area_m2=70,
        min_price=Decimal("200000"),
        max_price=Decimal("450000"),
        has_pool=False,
        has_garden=True,
        nearby_pois=(PoiCategory.SCHOOL, PoiCategory.HOSPITAL),
    )
    packed = msgpack.packb(to_parsed_query_dict(parsed), use_bin_type=True)
    restored = from_parsed_query_dict(msgpack.unpackb(packed, raw=False))
    assert restored == parsed
    assert isinstance(restored.typology, Typology)
    assert isinstance(restored.min_price, Decimal)
    assert all(isinstance(c, PoiCategory) for c in restored.nearby_pois)
    assert isinstance(restored.nearby_pois, tuple)


def test_search_result_roundtrip_through_msgpack():
    result = CachedSearchResult(
        parsed=ParsedQuery(free_text_remainder="hospital"),
        ranked_ids=[uuid4() for _ in range(5)],
    )
    packed = msgpack.packb(to_search_result_dict(result), use_bin_type=True)
    restored = from_search_result_dict(msgpack.unpackb(packed, raw=False))
    assert restored == result
    # Crucial — ranked_ids must come back as UUIDs (not str) for the
    # use case's order-preserving sort to work.
    assert all(isinstance(i, type(result.ranked_ids[0])) for i in restored.ranked_ids)
