"""LocationFilter invariant tests.

Spec `2026-05-listing-semantic-search-read-path` §Acceptance criteria
→ Domain invariants. The 422 route-side guard exists so the empty
case never reaches construction; `__post_init__` is last-line
defense and these tests pin it.
"""

import pytest

from listings.domain.exceptions import EmptyLocationFilterError
from listings.domain.location_filter import LocationFilter


def test_all_none_raises():
    with pytest.raises(EmptyLocationFilterError):
        LocationFilter(parish=None, municipality=None, district=None)


def test_default_construction_raises():
    with pytest.raises(EmptyLocationFilterError):
        LocationFilter()


def test_parish_only_ok():
    f = LocationFilter(parish="Cascais")
    assert f.parish == "Cascais"
    assert f.municipality is None
    assert f.district is None


def test_municipality_only_ok():
    f = LocationFilter(municipality="Cascais")
    assert f.municipality == "Cascais"


def test_district_only_ok():
    f = LocationFilter(district="Lisboa")
    assert f.district == "Lisboa"


def test_all_three_levels_ok():
    f = LocationFilter(parish="Estoril", municipality="Cascais", district="Lisboa")
    assert (f.parish, f.municipality, f.district) == ("Estoril", "Cascais", "Lisboa")


def test_empty_string_treated_as_unset():
    """Empty strings are falsy and don't satisfy the invariant —
    avoids the FE accidentally sending `?parish=` and bypassing
    the guard."""
    with pytest.raises(EmptyLocationFilterError):
        LocationFilter(parish="", municipality="", district="")


def test_frozen():
    """Value object — mutation raises."""
    f = LocationFilter(parish="Cascais")
    with pytest.raises(Exception):
        f.parish = "Estoril"  # type: ignore[misc]
