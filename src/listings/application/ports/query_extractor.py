"""`QueryExtractor` port — structured extraction from free-text queries.

Replaces ADR-013 v1's `QueryUnderstandingService.rewrite(str) -> str`
(text → text rewriting) with `QueryExtractor.extract(str) -> ParsedQuery`
(text → typed structured output). The use case sees the structural
facets the user explicitly mentioned and can hard-filter on them
at the SQL pre-filter stage; everything else lands in
`ParsedQuery.free_text_remainder` and becomes the soft cosine signal.

Two adapters:
- `LangChainQueryExtractor` (production) — `gpt-4o-mini` with
  structured output via a private Pydantic envelope.
- `IdentityQueryExtractor` (tests + `LISTINGS_SEARCH_ENABLED=false`)
  — returns `ParsedQuery(free_text_remainder=query)`.

Implementations MAY raise on failure (timeout, rate limit, network).
The calling use case (`SearchListings`) wraps the call in
try/except and falls back to `ParsedQuery(free_text_remainder=query)`
so search still runs, just less smart.

Spec: `2026-05-listing-search-structured-extraction` §1.
"""

from __future__ import annotations

from typing import Protocol

from listings.domain.parsed_query import ParsedQuery


class QueryExtractor(Protocol):
    async def extract(self, query: str) -> ParsedQuery:
        """Parse the user's raw free-text query into a typed
        `ParsedQuery`. Implementations MAY raise on failure — the
        calling use case is responsible for the fail-open envelope.
        """
        ...
