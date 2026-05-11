"""Always-miss adapter for `ListingsPageCache`.

Wired in the container when `LISTINGS_PAGE_CACHE_ENABLED=false` so
the use case's `get`/`set` calls stay structurally identical to the
Redis path — but every read is a miss and every write is a no-op.
Cleaner than a `cache is None` branch sprinkled through the use case.
"""

from __future__ import annotations

from listings.application.ports.listings_page_cache import CachedPage


class NullListingsPageCache:
    async def get(self, key: str) -> CachedPage | None:
        return None

    async def set(self, key: str, page: CachedPage, ttl_seconds: int) -> None:
        return None

    async def invalidate_namespace(self, namespace: str) -> None:
        return None
