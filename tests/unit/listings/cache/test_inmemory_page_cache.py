"""`InMemoryListingsPageCache` contract tests.

Covers get/set round-trip, miss returns None, TTL expiry, and
invalidate_namespace's prefix-scan semantics.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from listings.adapters.inmemory.inmemory_page_cache import InMemoryListingsPageCache
from listings.application.ports.listings_page_cache import CachedPage
from listings.domain.models import ListingType, PropertyStatus, Typology
from listings.domain.property_listing import PropertyListing


def _make_listing() -> PropertyListing:
    return PropertyListing(
        id=uuid4(),
        organization_id=uuid4(),
        status=PropertyStatus.ACTIVE,
        listing_type=ListingType.SALE,
        typology=Typology.APARTMENT,
        parish=None,
        municipality=None,
        district=None,
        location_enriched_at=None,
        location_enrichment_attempts=0,
        num_of_bedrooms=None,
        num_of_bathrooms=None,
        area_in_m2=None,
        has_pool=None,
        has_garden=None,
        has_elevator=None,
        min_price=None,
        first_image_s3_key=None,
        description=None,
        latitude=None,
        longitude=None,
        source_aggregate_version=1,
        source_occurred_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


async def test_miss_returns_none():
    cache = InMemoryListingsPageCache()
    assert await cache.get("never-set") is None


async def test_set_then_get_roundtrip():
    cache = InMemoryListingsPageCache()
    page = CachedPage(items=[_make_listing()], next_cursor="next-token")
    await cache.set("k1", page, ttl_seconds=10)
    assert await cache.get("k1") == page


async def test_ttl_expiry():
    cache = InMemoryListingsPageCache()
    page = CachedPage(items=[], next_cursor=None)
    await cache.set("k1", page, ttl_seconds=0)
    # Yield to the event loop so the monotonic clock advances even
    # by a sliver; ttl_seconds=0 means immediately expired.
    await asyncio.sleep(0.001)
    assert await cache.get("k1") is None


async def test_invalidate_namespace_drops_matching_keys():
    cache = InMemoryListingsPageCache()
    p = CachedPage(items=[], next_cursor=None)
    await cache.set("listings:list:v1:fp1:head:20", p, ttl_seconds=60)
    await cache.set("listings:list:v1:fp2:head:20", p, ttl_seconds=60)
    await cache.set("listings:search:v1:fp3", p, ttl_seconds=60)
    await cache.invalidate_namespace("listings:list:v1")
    assert await cache.get("listings:list:v1:fp1:head:20") is None
    assert await cache.get("listings:list:v1:fp2:head:20") is None
    assert await cache.get("listings:search:v1:fp3") == p
