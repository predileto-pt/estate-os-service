"""ParsedQuery defaults + frozen-ness.

The value object is intentionally invariant-free — every field is
optional and `ParsedQuery()` (all defaults) is the fail-open path
when the extractor errors. The route layer wraps the extractor in
try/except and substitutes `ParsedQuery(free_text_remainder=query)`,
so we just need to make sure construction works and the dataclass
is truly frozen.

Spec: `2026-05-listing-search-structured-extraction` §2.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from listings.domain.models import Typology
from listings.domain.parsed_query import ParsedQuery
from listings.domain.poi_category import PoiCategory


def test_default_construction_is_empty():
    pq = ParsedQuery()
    assert pq.free_text_remainder == ""
    assert pq.typology is None
    assert pq.min_bedrooms is None
    assert pq.min_bathrooms is None
    assert pq.min_area_m2 is None
    assert pq.max_area_m2 is None
    assert pq.min_price is None
    assert pq.max_price is None
    assert pq.has_pool is None
    assert pq.has_garden is None
    assert pq.has_elevator is None
    assert pq.has_parking is None
    assert pq.nearby_pois == ()


def test_construction_with_all_fields():
    pq = ParsedQuery(
        free_text_remainder="varanda",
        typology=Typology.HOUSE,
        min_bedrooms=3,
        min_bathrooms=2,
        min_area_m2=100,
        max_area_m2=200,
        min_price=Decimal("250000"),
        max_price=Decimal("500000"),
        has_pool=True,
        has_garden=True,
        has_elevator=False,
        has_parking=True,
        nearby_pois=(PoiCategory.SCHOOL, PoiCategory.GYM),
    )
    assert pq.typology == Typology.HOUSE
    assert pq.min_bedrooms == 3
    assert pq.nearby_pois == (PoiCategory.SCHOOL, PoiCategory.GYM)


def test_frozen_attribute_assignment_raises():
    pq = ParsedQuery(min_bedrooms=3)
    with pytest.raises(Exception):  # FrozenInstanceError, dataclasses
        pq.min_bedrooms = 5  # type: ignore[misc]


def test_zero_price_is_preserved():
    """Decimal(0) is falsy — sanity that the dataclass doesn't
    swallow it. The SQL filter builder uses `is not None`
    comparisons, not truthy-checks, so 0 round-trips."""
    pq = ParsedQuery(min_price=Decimal("0"))
    assert pq.min_price == Decimal("0")
    assert pq.min_price is not None


def test_fallback_construction_pattern():
    """The use-case fail-open pattern: extractor failed, fall back to
    raw query in the description. This is the most-used non-default
    construction."""
    pq = ParsedQuery(free_text_remainder="casa com piscina")
    assert pq.free_text_remainder == "casa com piscina"
    assert pq.typology is None
    assert pq.nearby_pois == ()
