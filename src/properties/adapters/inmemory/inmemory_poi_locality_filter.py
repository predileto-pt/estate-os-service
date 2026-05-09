"""Test double for `PoiLocalityFilter`.

Two flavors used across the suite:
- `KeepAllPoiLocalityFilter` — the default identity filter, asserts
  the use case still wires the filter correctly without affecting
  outcomes.
- `DropByPlaceIdPoiLocalityFilter` — drops candidates whose `place_id`
  is in a configured set. Lets a single test prove rows actually flow
  through the filter and disappear when rejected.
"""

from __future__ import annotations

from properties.application.ports.poi_locality_filter import (
    PoiCandidate,
    PoiLocalityFilter,
)
from properties.domain.services.locality_scope import LocalityKind


class KeepAllPoiLocalityFilter(PoiLocalityFilter):
    async def keep_in_locality(
        self,
        *,
        property_address: str,
        country: str,
        locality_kind: LocalityKind,
        candidates: list[PoiCandidate],
    ) -> list[PoiCandidate]:
        return list(candidates)


class DropByPlaceIdPoiLocalityFilter(PoiLocalityFilter):
    """Drops candidates whose `place_id` matches the configured set.
    Records the last call so tests can assert what was sent in.
    """

    def __init__(self, drop_place_ids: set[str] | None = None) -> None:
        self._drop = drop_place_ids or set()
        self.calls: list[
            tuple[str, str, LocalityKind, tuple[PoiCandidate, ...]]
        ] = []

    async def keep_in_locality(
        self,
        *,
        property_address: str,
        country: str,
        locality_kind: LocalityKind,
        candidates: list[PoiCandidate],
    ) -> list[PoiCandidate]:
        self.calls.append((property_address, country, locality_kind, tuple(candidates)))
        return [c for c in candidates if c.place_id not in self._drop]
