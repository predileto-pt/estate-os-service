"""Public list endpoint use case.

Reads from the `property_listings` projection via the keyset-paginated
repo method, in front of a Redis page cache. The route computes the
filter `fp` once and passes it down — the use case treats it as
opaque (the canonical inputs producing it live in `cursor.py`).

ADR-016 + spec `2026-05-listings-cursor-pagination-and-page-cache`.
"""

from __future__ import annotations

import structlog

from listings.application.ports.listings_page_cache import (
    CachedPage,
    ListingsPageCache,
)
from listings.application.ports.repositories.property_listing_repository import (
    PropertyListingRepository,
)
from listings.domain.pagination import (
    ListCursor,
    build_list_cache_key,
    encode,
)
from listings.domain.property_filters import PropertyFilters

log = structlog.get_logger()


class ListProperties:
    def __init__(
        self,
        *,
        property_listing_repo: PropertyListingRepository,
        cache: ListingsPageCache,
        ttl_seconds: int,
    ) -> None:
        self._property_listing_repo = property_listing_repo
        self._cache = cache
        self._ttl = ttl_seconds

    async def execute(
        self,
        *,
        fp: str,
        filters: PropertyFilters,
        cursor: ListCursor | None,
        limit: int,
    ) -> CachedPage:
        key = build_list_cache_key(fp=fp, cursor=cursor, limit=limit)

        hit = await self._cache.get(key)
        if hit is not None:
            log.info("listings_page_cache.hit", key_fp=key[-16:], kind="list")
            return hit

        items, has_more = await self._property_listing_repo.list_active_keyset(
            filters=filters, cursor=cursor, limit=limit,
        )
        next_cursor: str | None = None
        if has_more and items:
            tail = items[-1]
            next_cursor = encode(
                ListCursor(fp=fp, created_at=tail.created_at, id=tail.id)
            )

        page = CachedPage(items=items, next_cursor=next_cursor)
        await self._cache.set(key, page, self._ttl)
        log.info(
            "listings_page_cache.miss",
            key_fp=key[-16:],
            kind="list",
            items=len(items),
            has_more=has_more,
        )
        return page
