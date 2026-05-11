"""`InMemorySearchResultCache` contract tests."""

from __future__ import annotations

import asyncio
from uuid import uuid4

from listings.adapters.inmemory.inmemory_search_result_cache import (
    InMemorySearchResultCache,
)
from listings.application.ports.search_result_cache import CachedSearchResult
from listings.domain.parsed_query import ParsedQuery


async def test_miss_returns_none():
    cache = InMemorySearchResultCache()
    assert await cache.get("nope") is None


async def test_set_then_get_roundtrip():
    cache = InMemorySearchResultCache()
    result = CachedSearchResult(
        parsed=ParsedQuery(free_text_remainder="hospital"),
        ranked_ids=[uuid4(), uuid4()],
    )
    await cache.set("k", result, ttl_seconds=10)
    assert await cache.get("k") == result


async def test_ttl_expiry():
    cache = InMemorySearchResultCache()
    result = CachedSearchResult(parsed=ParsedQuery(), ranked_ids=[])
    await cache.set("k", result, ttl_seconds=0)
    await asyncio.sleep(0.001)
    assert await cache.get("k") is None


async def test_invalidate_namespace_drops_matching_keys():
    cache = InMemorySearchResultCache()
    r = CachedSearchResult(parsed=ParsedQuery(), ranked_ids=[])
    await cache.set("listings:search:v1:fp1", r, ttl_seconds=60)
    await cache.set("listings:search:v1:fp2", r, ttl_seconds=60)
    await cache.set("listings:list:v1:fp3:head:20", r, ttl_seconds=60)
    await cache.invalidate_namespace("listings:search:v1")
    assert await cache.get("listings:search:v1:fp1") is None
    assert await cache.get("listings:search:v1:fp2") is None
    assert await cache.get("listings:list:v1:fp3:head:20") == r
