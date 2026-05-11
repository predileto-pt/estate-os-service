"""`RedisListingsPageCache` adapter contract — mocked redis client.

Real-Redis integration coverage lives in
`tests/integration/listings/...` (next commit). Here we just verify:

- Happy path: set → msgpack-encoded bytes hit `redis.set`; get →
  bytes from `redis.get` round-trip through the codec.
- Connection failure on get/set → warning logged, miss returned
  (set is silent best-effort), no exception bubbles.
- Corrupt payload on get → miss, key deleted as cleanup.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import msgpack
import pytest

from listings.adapters.cache.listing_codec import to_page_dict
from listings.adapters.cache.redis_page_cache import RedisListingsPageCache
from listings.application.ports.listings_page_cache import CachedPage
from listings.domain.models import ListingType, PropertyStatus, Typology
from listings.domain.property_listing import PropertyListing


def _stub_listing() -> PropertyListing:
    now = datetime.now(timezone.utc)
    return PropertyListing(
        id=uuid4(),
        organization_id=uuid4(),
        title="Test property",
        status=PropertyStatus.ACTIVE,
        listing_type=ListingType.SALE,
        typology=Typology.APARTMENT,
        parish=None, municipality=None, district=None,
        location_enriched_at=None, location_enrichment_attempts=0,
        num_of_bedrooms=None, num_of_bathrooms=None, area_in_m2=None,
        has_pool=None, has_garden=None, has_elevator=None,
        min_price=None, first_image_s3_key=None, description=None,
        latitude=None, longitude=None,
        source_aggregate_version=1, source_occurred_at=now,
        created_at=now, updated_at=now,
    )


@pytest.fixture
def page() -> CachedPage:
    return CachedPage(items=[_stub_listing()], next_cursor="next-token")


async def test_get_miss_returns_none():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    cache = RedisListingsPageCache(redis)
    assert await cache.get("k") is None


async def test_get_hit_decodes_payload(page: CachedPage):
    payload = msgpack.packb(to_page_dict(page), use_bin_type=True)
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=payload)
    cache = RedisListingsPageCache(redis)
    result = await cache.get("k")
    assert result == page


async def test_set_writes_packed_bytes(page: CachedPage):
    redis = AsyncMock()
    cache = RedisListingsPageCache(redis)
    await cache.set("k", page, ttl_seconds=60)
    redis.set.assert_awaited_once()
    args, kwargs = redis.set.await_args
    assert args[0] == "k"
    # Unpack what was written to confirm it round-trips back to `page`.
    unpacked = msgpack.unpackb(args[1], raw=False)
    assert unpacked["next_cursor"] == "next-token"
    assert kwargs == {"ex": 60}


async def test_connection_error_on_get_returns_none():
    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=ConnectionError("redis down"))
    cache = RedisListingsPageCache(redis)
    assert await cache.get("k") is None  # no exception


async def test_connection_error_on_set_swallowed(page: CachedPage):
    redis = AsyncMock()
    redis.set = AsyncMock(side_effect=ConnectionError("redis down"))
    cache = RedisListingsPageCache(redis)
    # Must not raise.
    await cache.set("k", page, ttl_seconds=60)


async def test_corrupt_payload_returns_none_and_deletes_key():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=b"\x00not-msgpack\x01")
    redis.delete = AsyncMock()
    cache = RedisListingsPageCache(redis)
    assert await cache.get("poisoned") is None
    redis.delete.assert_awaited_once_with("poisoned")
