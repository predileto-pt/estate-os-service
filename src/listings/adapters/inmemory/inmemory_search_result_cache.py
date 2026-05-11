"""In-memory `SearchResultCache` for unit tests.

Dict + monotonic-time TTL. Same shape as `InMemoryListingsPageCache`
— a separate file rather than a generic helper so type-checking
stays sharp at the call sites.
"""

from __future__ import annotations

import time

from listings.application.ports.search_result_cache import CachedSearchResult


class InMemorySearchResultCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[CachedSearchResult, float]] = {}

    async def get(self, key: str) -> CachedSearchResult | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        result, expires_at = entry
        if time.monotonic() >= expires_at:
            self._store.pop(key, None)
            return None
        return result

    async def set(self, key: str, result: CachedSearchResult, ttl_seconds: int) -> None:
        self._store[key] = (result, time.monotonic() + ttl_seconds)

    async def invalidate_namespace(self, namespace: str) -> None:
        for key in [k for k in self._store if k.startswith(namespace)]:
            self._store.pop(key, None)
