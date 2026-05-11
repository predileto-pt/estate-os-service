"""`ParsedQuery` — structured extraction output for the search read path.

Returned by `QueryExtractor.extract(raw_query: str) -> ParsedQuery`.
Carries everything the LLM could pull out of the user's free-text
query, in a form the SQL pre-filter and the canonical-text-shaped
embed string can both consume:

- Structural facets the user explicitly mentioned (typology,
  bedroom/bathroom counts, area range, price range, boolean
  amenities) → become soft-hard SQL filters and renderable
  CHARACTERISTICS:/FEATURES: lines in the embed string.
- POI categories from the closed `PoiCategory` vocabulary →
  rendered into the NEARBY: line and used for the per-result
  matched/unmatched response composition.
- `free_text_remainder` — everything left after extraction (off-
  vocabulary POIs, colloquial qualifiers like "jeitoso", filler
  the LLM was asked to keep). Renders into the DESCRIPTION: line
  so cosine can still do something with the soft signal.

All fields default to None / "" / empty tuple. `ParsedQuery()` is
the fail-open default when extraction fails — the use case wraps
the extractor in try/except and substitutes
`ParsedQuery(free_text_remainder=raw_query)` so search still
runs, just less smart.

Spec: `2026-05-listing-search-structured-extraction` §2.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from listings.domain.models import Typology
from listings.domain.poi_category import PoiCategory


@dataclass(frozen=True)
class ParsedQuery:
    free_text_remainder: str = ""
    typology: Typology | None = None
    min_bedrooms: int | None = None
    min_bathrooms: int | None = None
    min_area_m2: int | None = None
    max_area_m2: int | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    has_pool: bool | None = None
    has_garden: bool | None = None
    has_elevator: bool | None = None
    has_parking: bool | None = None
    # TODO: min_parking_spaces: int | None — land once query-corpus
    # data shows users actually ask for exact parking counts (e.g.
    # "com 2 lugares de garagem"). Adding it later is additive on
    # this value object; the LLM prompt + SQL filter builder follow.
    nearby_pois: tuple[PoiCategory, ...] = ()
