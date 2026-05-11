"""In-memory `ListingsPageCache` for unit tests.

Dict + monotonic-time TTL. Not thread-safe — fine for asyncio
single-event-loop tests. Use `RedisListingsPageCache` for anything
real.

`invalidate_namespace` does a naive prefix scan because the
namespaces we care about are short (`listings:list:v1`).
"""

from __future__ import annotations

import time

from listings.application.ports.listings_page_cache import CachedPage


class InMemoryListingsPageCache:
    def __init__(self) -> None:
        # value = (CachedPage, expires_at_monotonic)
        self._store: dict[str, tuple[CachedPage, float]] = {}

    async def get(self, key: str) -> CachedPage | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        page, expires_at = entry
        if time.monotonic() >= expires_at:
            self._store.pop(key, None)
            return None
        return page

    async def set(self, key: str, page: CachedPage, ttl_seconds: int) -> None:
        self._store[key] = (page, time.monotonic() + ttl_seconds)

    async def invalidate_namespace(self, namespace: str) -> None:
        for key in [k for k in self._store if k.startswith(namespace)]:
            self._store.pop(key, None)
