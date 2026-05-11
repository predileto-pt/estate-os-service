"""`SearchResultCache` port — caches the search read path's
`(parsed_query, ranked_ids)` envelope.

Unlike `ListingsPageCache`, we don't cache hydrated pages here.
Why: after a hit on `(q, filters)`, each page is just a Redis GET +
a `WHERE id IN (...)` hydrate. The DB lookup for 20 PK reads is
sub-millisecond; an additional page-level cache would buy ~1 ms at
the cost of memory + invalidation surface.

`CachedSearchResult` is atomic — `parsed` and `ranked_ids` are
written together and read together so there's no TTL-drift recovery
branch (which an earlier two-port design needed). A cache hit means
**no LLM call AND no Pinecone call** for any page of the same
`(q, filters)` combination within the TTL window.

Consumed by `SearchListings` only. ParsedQuery lives at
`src/listings/domain/parsed_query.py` (ADR-014).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from listings.domain.parsed_query import ParsedQuery


@dataclass(frozen=True)
class CachedSearchResult:
    parsed: ParsedQuery
    ranked_ids: list[UUID]


class SearchResultCache(Protocol):
    async def get(self, key: str) -> CachedSearchResult | None: ...
    async def set(self, key: str, result: CachedSearchResult, ttl_seconds: int) -> None: ...
    async def invalidate_namespace(self, namespace: str) -> None: ...
