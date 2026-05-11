"""`RedisSearchResultCache` adapter contract — mocked redis client."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import msgpack

from listings.adapters.cache.listing_codec import to_search_result_dict
from listings.adapters.cache.redis_search_result_cache import RedisSearchResultCache
from listings.application.ports.search_result_cache import CachedSearchResult
from listings.domain.parsed_query import ParsedQuery


def _stub_result() -> CachedSearchResult:
    return CachedSearchResult(
        parsed=ParsedQuery(free_text_remainder="hospital"),
        ranked_ids=[uuid4(), uuid4(), uuid4()],
    )


async def test_get_miss_returns_none():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    cache = RedisSearchResultCache(redis)
    assert await cache.get("k") is None


async def test_get_hit_decodes_payload():
    result = _stub_result()
    payload = msgpack.packb(to_search_result_dict(result), use_bin_type=True)
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=payload)
    cache = RedisSearchResultCache(redis)
    assert await cache.get("k") == result


async def test_set_writes_packed_bytes():
    result = _stub_result()
    redis = AsyncMock()
    cache = RedisSearchResultCache(redis)
    await cache.set("k", result, ttl_seconds=90)
    redis.set.assert_awaited_once()
    args, kwargs = redis.set.await_args
    assert args[0] == "k"
    unpacked = msgpack.unpackb(args[1], raw=False)
    assert len(unpacked["ranked_ids"]) == 3
    assert kwargs == {"ex": 90}


async def test_connection_error_on_get_returns_none():
    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=ConnectionError("redis down"))
    cache = RedisSearchResultCache(redis)
    assert await cache.get("k") is None


async def test_corrupt_payload_returns_none_and_deletes_key():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=b"not-msgpack")
    redis.delete = AsyncMock()
    cache = RedisSearchResultCache(redis)
    assert await cache.get("poisoned") is None
    redis.delete.assert_awaited_once_with("poisoned")
