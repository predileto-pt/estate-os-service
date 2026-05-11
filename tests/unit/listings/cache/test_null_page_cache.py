"""`NullListingsPageCache` is the "cache is off" adapter — every
get/set/invalidate is a no-op. Three trivial assertions confirm the
contract."""

from __future__ import annotations

from listings.adapters.cache.null_page_cache import NullListingsPageCache
from listings.application.ports.listings_page_cache import CachedPage


async def test_get_always_misses():
    cache = NullListingsPageCache()
    assert await cache.get("anything") is None


async def test_set_is_noop_so_subsequent_get_still_misses():
    cache = NullListingsPageCache()
    await cache.set("k", CachedPage(items=[], next_cursor=None), ttl_seconds=60)
    assert await cache.get("k") is None


async def test_invalidate_namespace_is_noop():
    cache = NullListingsPageCache()
    # Just confirm it doesn't raise.
    await cache.invalidate_namespace("listings:list:v1")
