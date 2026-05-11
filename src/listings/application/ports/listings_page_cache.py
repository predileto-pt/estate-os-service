"""`ListingsPageCache` port — caches hydrated pages from the list path.

The cached value (`CachedPage`) carries the page's items plus the
already-encoded `next_cursor` string, so a cache hit returns the full
response shape with no recomputation. Keyed on `(fp, cursor, limit)`
by the caller via `build_list_cache_key`.

Consumed by `ListProperties` only. The search path uses
`SearchResultCache` instead (a different shape — see
`search_result_cache.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from listings.domain.property_listing import PropertyListing


@dataclass(frozen=True)
class CachedPage:
    """One page of list results in cache-stored form.

    `next_cursor` is the encoded token (string) ready to return on
    the wire — not the typed `ListCursor` — so a cache hit returns
    items + cursor without re-encoding.
    """

    items: list[PropertyListing]
    next_cursor: str | None


class ListingsPageCache(Protocol):
    async def get(self, key: str) -> CachedPage | None: ...
    async def set(self, key: str, page: CachedPage, ttl_seconds: int) -> None: ...
    async def invalidate_namespace(self, namespace: str) -> None: ...
