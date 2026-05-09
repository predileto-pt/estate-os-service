"""Pure-function tests for the (country, category) → policy resolver."""

from __future__ import annotations

import pytest

from properties.domain.models.property_poi import PoiCategory
from properties.domain.services.poi_discovery_policy import (
    DEFAULT_POLICY,
    MUNICIPALITY_WIDE_POLICY,
    Country,
    resolve_discovery_policy,
)


class TestPortugalMunicipalityWideCategories:
    """Categories that surface every match within a typical PT municipality."""

    @pytest.mark.parametrize(
        "category",
        [
            PoiCategory.RESTAURANT,
            PoiCategory.COFFEE_SHOP,
            PoiCategory.GYM,
            PoiCategory.HOSPITAL,
            PoiCategory.PHARMACY,
            PoiCategory.SCHOOL,
            PoiCategory.TIRE_SHOP,
            PoiCategory.AUTO_SHOP,
        ],
    )
    def test_resolves_to_municipality_wide_for_pt(self, category: PoiCategory) -> None:
        assert resolve_discovery_policy(Country.PORTUGAL, category) is MUNICIPALITY_WIDE_POLICY

    def test_municipality_policy_is_unbounded(self) -> None:
        assert MUNICIPALITY_WIDE_POLICY.result_limit is None
        # Comfortably contains every typical PT municipality without
        # exceeding Google's 50_000m cap.
        assert 5000 < MUNICIPALITY_WIDE_POLICY.radius_meters <= 50_000

    def test_string_country_works_without_enum(self) -> None:
        # Free-text country (matches what listings carries today).
        assert (
            resolve_discovery_policy("Portugal", PoiCategory.RESTAURANT) is MUNICIPALITY_WIDE_POLICY
        )


class TestDefaultPolicyFallback:
    """Categories outside the PT municipality-wide set get the focused default."""

    @pytest.mark.parametrize(
        "category",
        [
            PoiCategory.BANK,
            PoiCategory.GROCERY,
            PoiCategory.LAUNDRY,
            PoiCategory.GAS_STATION,
            PoiCategory.PUBLIC_TRANSIT,
            PoiCategory.KINDERGARTEN,
            PoiCategory.PARK,
            PoiCategory.POST_OFFICE,
            PoiCategory.LIBRARY,
            PoiCategory.SHOPPING_MALL,
            PoiCategory.BAKERY,
            PoiCategory.POLICE_STATION,
        ],
    )
    def test_pt_non_wide_category_uses_default(self, category: PoiCategory) -> None:
        assert resolve_discovery_policy(Country.PORTUGAL, category) is DEFAULT_POLICY

    def test_unknown_country_uses_default_even_for_wide_category(self) -> None:
        # The wide-category set is PT-specific. Other countries fall back.
        assert resolve_discovery_policy("Spain", PoiCategory.RESTAURANT) is DEFAULT_POLICY

    def test_none_country_uses_default(self) -> None:
        assert resolve_discovery_policy(None, PoiCategory.RESTAURANT) is DEFAULT_POLICY

    def test_default_policy_has_finite_limit(self) -> None:
        assert DEFAULT_POLICY.result_limit is not None
        assert DEFAULT_POLICY.result_limit > 0
