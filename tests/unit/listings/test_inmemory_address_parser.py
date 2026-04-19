"""Unit tests for `InMemoryAddressParser` — the deterministic test fake.

Splits on `,` and assigns the first three chunks to
parish / municipality / district. Worth testing because every unit + integration
test in this module relies on the split being exactly as expected.
"""

import pytest

from listings.adapters.inmemory.inmemory_address_parser import InMemoryAddressParser


@pytest.fixture
def parser():
    return InMemoryAddressParser()


async def test_three_chunks_assigned_in_order(parser):
    result = await parser.parse("Arca, Ponte de Lima, Viana do Castelo")
    assert result.parish == "Arca"
    assert result.municipality == "Ponte de Lima"
    assert result.district == "Viana do Castelo"


async def test_two_chunks_leaves_district_null(parser):
    result = await parser.parse("Rua Augusta 1, Lisboa")
    assert result.parish == "Rua Augusta 1"
    assert result.municipality == "Lisboa"
    assert result.district is None


async def test_single_chunk_leaves_municipality_and_district_null(parser):
    result = await parser.parse("Somewhere")
    assert result.parish == "Somewhere"
    assert result.municipality is None
    assert result.district is None


async def test_extra_chunks_beyond_three_are_ignored(parser):
    result = await parser.parse("A, B, C, D, E")
    assert result.parish == "A"
    assert result.municipality == "B"
    assert result.district == "C"


async def test_strips_whitespace_around_chunks(parser):
    result = await parser.parse("  Parish  ,  Municipality  ,  District  ")
    assert result.parish == "Parish"
    assert result.municipality == "Municipality"
    assert result.district == "District"
