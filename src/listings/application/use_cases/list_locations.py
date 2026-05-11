"""`ListLocations` — hierarchical location tree for the FE selector.

Reads distinct (parish, municipality, district) triples from the
`property_listings` projection and groups them into the shape
expected by the `/api/v1/listings/locations` endpoint:

```
{
  "districts": [
    {"name": "Lisboa", "municipalities": [
      {"name": "Cascais", "parishes": ["Cascais", "Estoril", ...]},
      ...
    ]},
    ...
  ]
}
```

A TTL cache (default 5 minutes, configurable via
`LISTINGS_LOCATIONS_CACHE_TTL_SECONDS`) keeps the response cheap
since populated locations don't churn fast. The cache is process-
local — each instance warms its own copy.

Spec: `2026-05-listing-semantic-search-read-path` §"`GET
/api/v1/listings/locations`".
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from listings.application.ports.repositories.property_listing_repository import (
    PropertyListingRepository,
)


@dataclass(frozen=True)
class _Municipality:
    name: str
    parishes: list[str]


@dataclass(frozen=True)
class _District:
    name: str
    municipalities: list[_Municipality]


@dataclass(frozen=True)
class LocationTree:
    """Use-case output. The route layer maps this to the JSON
    response schema."""

    districts: list[_District]


class ListLocations:
    def __init__(
        self,
        *,
        property_listing_repo: PropertyListingRepository,
        ttl_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._property_listing_repo = property_listing_repo
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._cached: LocationTree | None = None
        self._cached_at: float | None = None

    async def execute(self) -> LocationTree:
        now = self._clock()
        if (
            self._cached is not None
            and self._cached_at is not None
            and now - self._cached_at < self._ttl_seconds
        ):
            return self._cached

        triples = await self._property_listing_repo.list_locations()
        tree = _build_tree(triples)
        self._cached = tree
        self._cached_at = now
        return tree


def _build_tree(triples) -> LocationTree:
    """Group flat triples into district → municipality → parish.

    Triples with missing levels still surface — a row with only a
    district populated contributes the district (with an empty
    municipalities list) so the FE can offer it as a top-level
    filter. Sorted alphabetically at each level, case-insensitive
    on the visible name."""
    # district name → municipality name → set of parish names
    by_district: dict[str, dict[str | None, set[str | None]]] = {}

    for t in triples:
        d = t.district
        if d is None:
            # No district anchor — can't slot under the hierarchical tree.
            # Spec keeps the dropdown hierarchical; rows with NULL
            # district are unreachable from the selector but remain
            # searchable via parish/municipality directly. Skip for the
            # tree, log if desired by the route layer.
            continue
        by_district.setdefault(d, {})
        muni = t.municipality
        by_district[d].setdefault(muni, set())
        if t.parish is not None:
            by_district[d][muni].add(t.parish)

    districts: list[_District] = []
    for district_name in sorted(by_district.keys(), key=str.casefold):
        muni_map = by_district[district_name]
        municipalities: list[_Municipality] = []
        # `None` municipality bucket would render as a top-level
        # district-only entry; skip it for the v1 hierarchical tree
        # (it's still reachable via `?district=`).
        non_null_munis: list[str] = [m for m in muni_map.keys() if m is not None]
        for muni_name in sorted(non_null_munis, key=str.casefold):
            non_null_parishes: list[str] = [p for p in muni_map[muni_name] if p is not None]
            parishes = sorted(non_null_parishes, key=str.casefold)
            municipalities.append(_Municipality(name=muni_name, parishes=parishes))
        districts.append(_District(name=district_name, municipalities=municipalities))

    return LocationTree(districts=districts)
