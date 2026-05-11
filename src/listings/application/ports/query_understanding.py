"""`QueryUnderstandingService` port — rewrites free-text queries into
a retrieval-friendly form for the embedder.

Renamed from ADR-013's `QueryRewriter` to make the responsibility
explicit: the job is to take the user's raw free-text query (often
colloquial, possibly typo'd, mixed-language PT) and produce a
canonical retrieval form that aligns with the canonical-text
composer's PT vocabulary (NEARBY:/FEATURES:/etc.).

Two adapters in v1:
- `LangChainQueryUnderstandingService` — LLM-backed, used when
  `LISTINGS_SEARCH_ENABLED=true`.
- `IdentityQueryUnderstandingService` — returns input unchanged.
  Used in tests, and as the wired adapter whenever
  `LISTINGS_SEARCH_ENABLED=false` (the route ignores `q` while the
  flag is off, but the container always has a non-None service so
  the use-case wiring never branches on adapter presence).

The use case fail-opens on adapter errors via try/except — see
`SearchListings`. The adapter does NOT swallow errors on its own;
let raises bubble so the use case can log + degrade.

Spec: `2026-05-listing-semantic-search-read-path` §"Components to
build" 1-3.
"""

from __future__ import annotations

from typing import Protocol


class QueryUnderstandingService(Protocol):
    async def rewrite(self, query: str) -> str:
        """Return a retrieval-friendly form of `query`.

        Implementations MAY raise on failure (LLM timeout, rate
        limit, etc.) — the calling use case wraps the call in
        try/except and falls back to the raw query.
        """
        ...
