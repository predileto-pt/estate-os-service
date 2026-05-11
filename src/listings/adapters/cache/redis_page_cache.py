"""Redis-backed `ListingsPageCache`.

Value codec: msgpack on top of the primitive-dict helpers in
`listing_codec.py`. The whole adapter is best-effort — Redis being
down doesn't fail the request, just falls through to the DB. Same for
deserialization errors: log warning, treat as miss.
"""

from __future__ import annotations

import msgpack
import redis.asyncio as aioredis
import structlog

from listings.adapters.cache.listing_codec import from_page_dict, to_page_dict
from listings.application.ports.listings_page_cache import CachedPage

log = structlog.get_logger()


class RedisListingsPageCache:
    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis

    async def get(self, key: str) -> CachedPage | None:
        try:
            raw = await self._redis.get(key)
        except Exception as exc:
            log.warning("listings_page_cache.redis_get_failed", key_fp=key[-16:], error=str(exc))
            return None
        if raw is None:
            return None
        try:
            payload = msgpack.unpackb(raw, raw=False)
            return from_page_dict(payload)
        except Exception as exc:
            log.warning("listings_page_cache.decode_failed", key_fp=key[-16:], error=str(exc))
            # Best-effort cleanup of a poisoned key — don't propagate
            # failure if even the delete fails.
            try:
                await self._redis.delete(key)
            except Exception:
                pass
            return None

    async def set(self, key: str, page: CachedPage, ttl_seconds: int) -> None:
        try:
            payload = msgpack.packb(to_page_dict(page), use_bin_type=True)
            await self._redis.set(key, payload, ex=ttl_seconds)
        except Exception as exc:
            log.warning("listings_page_cache.redis_set_failed", key_fp=key[-16:], error=str(exc))

    async def invalidate_namespace(self, namespace: str) -> None:
        """Best-effort SCAN + DEL by prefix. Used by the v2 event-
        driven invalidation path; v1 callers use TTL only so this is
        currently unused."""
        try:
            pattern = f"{namespace}*"
            async for key in self._redis.scan_iter(match=pattern):
                await self._redis.delete(key)
        except Exception as exc:
            log.warning("listings_page_cache.invalidate_failed", namespace=namespace, error=str(exc))
