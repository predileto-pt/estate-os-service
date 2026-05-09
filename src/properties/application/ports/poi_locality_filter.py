"""Port: drop POIs whose address falls outside the property's locality.

A property in Lisboa can sit a few hundred metres from the boundary
with Oeiras or Loures — Google Nearby Search happily returns results
across those boundaries. Buyers asking "what schools are near MY
listing" expect to see only the same-locality matches.

Pure Protocol — the implementation may be an LLM call (default), a
geocoding-based polygon check, or a no-op test double. The use case
calls this once per property with all candidates batched together.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from properties.domain.services.locality_scope import LocalityKind


@dataclass(frozen=True)
class PoiCandidate:
    """The minimum signal an implementation needs to judge locality.

    Identity carries through `place_id` so the use case can map verdicts
    back to its in-flight `NearbyPlace` objects. `address` is whatever
    the provider returned — Google's `vicinity`, a formatted address,
    or an empty string when the provider didn't include one.
    """

    place_id: str
    name: str
    address: str


class PoiLocalityFilter(Protocol):
    """Return only the candidates that share the property's locality.

    The implementation is responsible for being country-aware:
    `LocalityKind.MUNICIPALITY` matches PT `concelho` boundaries,
    `LocalityKind.CITY` matches BR / US / generic city boundaries.

    Implementations should be defensive: when in doubt, KEEP the
    candidate. Dropping a real match is worse than keeping a
    cross-boundary one — the catalog can be edited manually, an
    over-aggressive filter erases data the user can't easily restore.
    """

    async def keep_in_locality(
        self,
        *,
        property_address: str,
        country: str,
        locality_kind: LocalityKind,
        candidates: list[PoiCandidate],
    ) -> list[PoiCandidate]: ...
