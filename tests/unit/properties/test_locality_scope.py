"""Pure-function tests for the country → LocalityKind resolver."""

from __future__ import annotations

import pytest

from properties.domain.services.locality_scope import (
    LocalityKind,
    resolve_locality_scope,
)


class TestResolveLocalityScope:
    def test_portugal_resolves_to_municipality(self) -> None:
        assert resolve_locality_scope("Portugal") is LocalityKind.MUNICIPALITY

    def test_portugal_with_padding_still_resolves(self) -> None:
        assert resolve_locality_scope("  Portugal  ") is LocalityKind.MUNICIPALITY

    @pytest.mark.parametrize("country", ["Brazil", "United States", "Spain", "France"])
    def test_other_countries_resolve_to_city(self, country: str) -> None:
        assert resolve_locality_scope(country) is LocalityKind.CITY

    @pytest.mark.parametrize("country", [None, "", "   "])
    def test_missing_country_falls_back_to_city(self, country: str | None) -> None:
        assert resolve_locality_scope(country) is LocalityKind.CITY
