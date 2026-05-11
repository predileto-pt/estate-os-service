"""`NullSearchResultCache` always-miss contract."""

from __future__ import annotations

from listings.adapters.cache.null_search_result_cache import NullSearchResultCache
from listings.application.ports.search_result_cache import CachedSearchResult
from listings.domain.parsed_query import ParsedQuery


async def test_get_always_misses():
    cache = NullSearchResultCache()
    assert await cache.get("any") is None


async def test_set_is_noop():
    cache = NullSearchResultCache()
    await cache.set("k", CachedSearchResult(parsed=ParsedQuery(), ranked_ids=[]), ttl_seconds=60)
    assert await cache.get("k") is None


async def test_invalidate_namespace_is_noop():
    cache = NullSearchResultCache()
    await cache.invalidate_namespace("listings:search:v1")
