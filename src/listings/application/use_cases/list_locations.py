"""`ListLocations` — static country catalog for the FE selector.

**Amended 2026-05-11.** Reads from a bundled JSON file
(`src/listings/static_data/locations.json`) instead of the
`property_listings` projection. Rationale:

- The FE selector needs to render the full geography from day one
  — even before any listings are indexed in a region.
- Locations are inherently stable. PT's parish/municipality
  catalog rarely changes (last reform: 2013).
- Cheaper than a query-time DISTINCT scan + no DB round-trip.

Trade-off: empty regions appear in the dropdown (the FE shows a
"no results" state when search returns 0).

Multi-country shape — v1 only ships Portugal populated. Future
countries are appended as additional entries in the JSON file.

Spec: `2026-05-listing-semantic-search-read-path` §"GET
/api/v1/listings/locations".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_CATALOG_PATH = Path(__file__).parent.parent.parent / "static_data" / "locations.json"


@dataclass(frozen=True)
class _Municipality:
    name: str
    parishes: list[str]


@dataclass(frozen=True)
class _District:
    name: str
    municipalities: list[_Municipality]


@dataclass(frozen=True)
class _Country:
    code: str
    name: str
    districts: list[_District]


@dataclass(frozen=True)
class LocationTree:
    """Use-case output. The route layer maps this to the JSON
    response schema (`LocationTreeResponse`)."""

    countries: list[_Country]


class ListLocations:
    def __init__(self, *, catalog_path: Path | None = None) -> None:
        path = catalog_path if catalog_path is not None else _DEFAULT_CATALOG_PATH
        self._tree = _load_tree(path)

    async def execute(self) -> LocationTree:
        return self._tree


def _load_tree(path: Path) -> LocationTree:
    raw = json.loads(path.read_text(encoding="utf-8"))
    countries: list[_Country] = []
    for c in raw.get("countries", []):
        districts: list[_District] = []
        for d in c.get("districts", []):
            municipalities: list[_Municipality] = []
            for m in d.get("municipalities", []):
                municipalities.append(
                    _Municipality(name=m["name"], parishes=list(m.get("parishes", [])))
                )
            districts.append(_District(name=d["name"], municipalities=municipalities))
        countries.append(_Country(code=c["code"], name=c["name"], districts=districts))
    return LocationTree(countries=countries)
