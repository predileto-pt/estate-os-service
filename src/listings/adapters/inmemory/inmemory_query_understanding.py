"""Identity `QueryUnderstandingService` — returns the input verbatim.

Two roles:
1. **Tests**: deterministic stub so test assertions don't depend on
   LLM output.
2. **`LISTINGS_SEARCH_ENABLED=false` wiring**: when the gate is off,
   the route ignores `q` anyway, so what's wired here is plumbing
   symmetry. Keeps the container's `query_understanding_service`
   non-None so the use case wiring never branches on adapter
   presence.

The production LLM-failure path is NOT handled by swapping to this
adapter at runtime — that's the `try/except` in `SearchListings`.

Spec: `2026-05-listing-semantic-search-read-path` §"Components to
build" #3.
"""

from __future__ import annotations

from listings.application.ports.query_understanding import QueryUnderstandingService


class IdentityQueryUnderstandingService(QueryUnderstandingService):
    async def rewrite(self, query: str) -> str:
        return query
