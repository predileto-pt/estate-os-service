"""Unit tests for the search-route validation helpers.

The integration suite covers the route-level 422; this file pins
the helper directly so a refactor that bypasses route-layer
validation gets caught immediately.

Spec: `2026-05-listing-semantic-search-read-path` §Test strategy.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from listings.adapters.api.search_validation import (
    normalize_query,
    validate_location_for_search,
)


class TestNormalizeQuery:
    def test_none_returns_none(self):
        assert normalize_query(None) is None

    def test_empty_returns_none(self):
        assert normalize_query("") is None

    def test_whitespace_only_returns_none(self):
        assert normalize_query("   \t\n  ") is None

    def test_strips_surrounding_whitespace(self):
        assert normalize_query("  casa com piscina  ") == "casa com piscina"

    def test_keeps_inner_whitespace(self):
        assert normalize_query("casa  com  piscina") == "casa  com  piscina"


class TestValidateLocationForSearch:
    def test_q_none_is_always_ok(self):
        # No q → no location required.
        validate_location_for_search(
            normalized_q=None, parish=None, municipality=None, district=None
        )

    def test_q_set_with_no_location_raises_422(self):
        with pytest.raises(HTTPException) as exc:
            validate_location_for_search(
                normalized_q="casa",
                parish=None,
                municipality=None,
                district=None,
            )
        assert exc.value.status_code == 422
        detail = exc.value.detail
        assert isinstance(detail, dict)
        assert detail["code"] == "location_required_for_search"
        assert "message" in detail

    def test_q_set_with_parish_ok(self):
        validate_location_for_search(
            normalized_q="casa", parish="Cascais", municipality=None, district=None
        )

    def test_q_set_with_municipality_ok(self):
        validate_location_for_search(
            normalized_q="casa", parish=None, municipality="Lisboa", district=None
        )

    def test_q_set_with_district_ok(self):
        validate_location_for_search(
            normalized_q="casa", parish=None, municipality=None, district="Porto"
        )

    def test_q_set_with_empty_string_location_is_falsy(self):
        """Empty-string `parish` (FE quirk: `?parish=`) shouldn't
        satisfy the requirement — falsy values fail the guard."""
        with pytest.raises(HTTPException) as exc:
            validate_location_for_search(
                normalized_q="casa", parish="", municipality="", district=""
            )
        assert exc.value.status_code == 422
