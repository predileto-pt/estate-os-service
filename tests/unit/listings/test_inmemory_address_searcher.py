"""Unit tests for `InMemoryAddressSearcher` — the deterministic test fake.

Splits canonical addresses into parish/municipality/district. Raises
when fewer than three chunks are present (no fallback synthesis —
spec 2026-05-property-address-enrichment-fix §Cross-cutting test
doubles: "raises when the test address can't yield non-null PT fields").
"""

import pytest

from listings.adapters.inmemory.inmemory_address_searcher import InMemoryAddressSearcher
from listings.application.ports.address_searcher import ParsedAddress


@pytest.fixture
def searcher():
    return InMemoryAddressSearcher()


async def test_canonical_three_chunks_yields_pt_envelope(searcher):
    parsed = await searcher.search(
        address="Arca, Ponte de Lima, Viana do Castelo",
        postal_code=None,
        country="Portugal",
    )
    assert isinstance(parsed, ParsedAddress)
    assert parsed.country == "Portugal"
    assert parsed.parish == "Arca"
    assert parsed.municipality == "Ponte de Lima"
    assert parsed.district == "Viana do Castelo"
    # US-shape fields all None for a PT result.
    assert parsed.city is None
    assert parsed.state is None


async def test_postal_code_passes_through_to_envelope(searcher):
    parsed = await searcher.search(
        address="Arca, Ponte de Lima, Viana do Castelo",
        postal_code="4990-001",
        country="Portugal",
    )
    assert parsed.postal_code == "4990-001"


async def test_two_chunks_raises(searcher):
    with pytest.raises(ValueError):
        await searcher.search(
            address="Lisboa, Lisboa",  # only 2 chunks — district can't be synthesized
            postal_code=None,
            country="Portugal",
        )


async def test_unsupported_country_raises(searcher):
    with pytest.raises(NotImplementedError):
        await searcher.search(
            address="123 Main St, Boston, MA",
            postal_code=None,
            country="United States",
        )
