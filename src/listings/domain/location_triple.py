"""`LocationTriple` — DB-row projection of (parish, municipality, district).

Returned by `PropertyListingRepository.list_locations()` for the
`/api/v1/listings/locations` endpoint. **No invariant**: address
enrichment can populate any subset of the three fields, and the
endpoint groups whatever's there into the hierarchical tree.

Distinct from `LocationFilter` (request-side value with the
at-least-one invariant). Same field shape, different semantics. See
spec `2026-05-listing-semantic-search-read-path` §"Components to
build" 4a.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LocationTriple:
    parish: str | None
    municipality: str | None
    district: str | None
