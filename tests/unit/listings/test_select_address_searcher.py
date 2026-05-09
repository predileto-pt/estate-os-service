"""Unit tests for the country-keyed AddressSearcher dispatcher.

Spec: 2026-05-property-address-enrichment-fix.md §AddressSearcher.
v1 implements only Portugal; everything else raises NotImplementedError.
"""

import pytest

from listings.adapters.inmemory.inmemory_address_searcher import InMemoryAddressSearcher
from listings.application.use_cases.select_address_searcher import select_address_searcher


def test_portugal_returns_the_pt_searcher():
    pt = InMemoryAddressSearcher()
    selected = select_address_searcher("Portugal", portugal=pt)
    assert selected is pt


def test_unsupported_country_raises_not_implemented():
    pt = InMemoryAddressSearcher()
    for country in ("United States", "Spain", "France", "", "portugal"):  # case-sensitive
        with pytest.raises(NotImplementedError):
            select_address_searcher(country, portugal=pt)
