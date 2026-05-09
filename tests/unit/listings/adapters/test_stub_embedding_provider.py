"""Sanity tests for the deterministic stub embedding provider."""

from __future__ import annotations

import math

from listings.adapters.embedding.stub_provider import StubEmbeddingProvider


async def test_same_text_same_vector():
    provider = StubEmbeddingProvider(dimensions=64)
    a = await provider.embed("hello world")
    b = await provider.embed("hello world")
    assert a == b


async def test_different_text_different_vector():
    provider = StubEmbeddingProvider(dimensions=64)
    a = await provider.embed("alpha")
    b = await provider.embed("beta")
    assert a != b


async def test_vector_has_requested_dimensions():
    provider = StubEmbeddingProvider(dimensions=128)
    v = await provider.embed("anything")
    assert len(v) == 128


async def test_vector_is_unit_normalized():
    provider = StubEmbeddingProvider(dimensions=128)
    v = await provider.embed("Rua Augusta 1, Lisboa")
    norm = math.sqrt(sum(x * x for x in v))
    assert abs(norm - 1.0) < 1e-9
