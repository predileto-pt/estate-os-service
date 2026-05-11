"""Identity `QueryExtractor` — returns the raw query in `free_text_remainder`.

Two roles:
1. **Tests**: deterministic stub so test assertions don't depend on
   LLM output.
2. **`LISTINGS_SEARCH_ENABLED=false` wiring**: when the gate is off
   the route ignores `q` anyway, so what's wired here is plumbing
   symmetry. Keeps the container's `query_extractor` non-None so
   the use-case wiring never branches on adapter presence.

The production LLM-failure path is NOT handled by swapping to this
adapter at runtime — that's the `try/except` in `SearchListings`.

Spec: `2026-05-listing-search-structured-extraction` §5.
"""

from __future__ import annotations

from listings.application.ports.query_extractor import QueryExtractor
from listings.domain.parsed_query import ParsedQuery


class IdentityQueryExtractor(QueryExtractor):
    async def extract(self, query: str) -> ParsedQuery:
        return ParsedQuery(free_text_remainder=query)
