"""Redis-backed `SearchResultCache`.

Stores the `(parsed_query, ranked_ids)` envelope so a single hit
covers any page of the same (q, filters). Best-effort error
handling — Redis down or decode failure → miss → use case falls
through to LLM + Pinecone.
"""

from __future__ import annotations

import msgpack
import redis.asyncio as aioredis
import structlog

from listings.adapters.cache.listing_codec import (
    from_search_result_dict,
    to_search_result_dict,
)
from listings.application.ports.search_result_cache import CachedSearchResult

log = structlog.get_logger()


class RedisSearchResultCache:
    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis

    async def get(self, key: str) -> CachedSearchResult | None:
        try:
            raw = await self._redis.get(key)
        except Exception as exc:
            log.warning(
                "search_result_cache.redis_get_failed",
                key_fp=key[-16:],
                error=str(exc),
            )
            return None
        if raw is None:
            return None
        try:
            payload = msgpack.unpackb(raw, raw=False)
            return from_search_result_dict(payload)
        except Exception as exc:
            log.warning("search_result_cache.decode_failed", key_fp=key[-16:], error=str(exc))
            try:
                await self._redis.delete(key)
            except Exception:
                pass
            return None

    async def set(self, key: str, result: CachedSearchResult, ttl_seconds: int) -> None:
        try:
            payload = msgpack.packb(to_search_result_dict(result), use_bin_type=True)
            await self._redis.set(key, payload, ex=ttl_seconds)
        except Exception as exc:
            log.warning("search_result_cache.redis_set_failed", key_fp=key[-16:], error=str(exc))

    async def invalidate_namespace(self, namespace: str) -> None:
        try:
            pattern = f"{namespace}*"
            async for key in self._redis.scan_iter(match=pattern):
                await self._redis.delete(key)
        except Exception as exc:
            log.warning(
                "search_result_cache.invalidate_failed",
                namespace=namespace,
                error=str(exc),
            )
