"""Always-miss adapter for `SearchResultCache`.

Wired when `LISTINGS_PAGE_CACHE_ENABLED=false` so `SearchListings`'s
get/set calls stay structurally identical to the Redis path — but
every read is a miss and every write is a no-op.
"""

from __future__ import annotations

from listings.application.ports.search_result_cache import CachedSearchResult


class NullSearchResultCache:
    async def get(self, key: str) -> CachedSearchResult | None:
        return None

    async def set(self, key: str, result: CachedSearchResult, ttl_seconds: int) -> None:
        return None

    async def invalidate_namespace(self, namespace: str) -> None:
        return None
