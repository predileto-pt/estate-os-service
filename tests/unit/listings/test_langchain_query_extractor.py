"""LangChain extractor tests.

We stub `_llm.ainvoke` to return canned `_ExtractorResult` payloads,
which exercises:
- The mapping from `_ExtractorResult` (Pydantic, list[PoiCategory])
  to `ParsedQuery` (frozen dataclass, tuple[PoiCategory, ...]).
- The timeout path (`asyncio.TimeoutError` raised when the underlying
  call exceeds the configured budget).
- The error-bubbling path (the adapter re-raises so the use case's
  fail-open envelope can catch it).

We DON'T test the prompt itself — that's an evaluation problem,
not a unit test. The spec calls for ~10 worked examples in the
prompt, which the integration tests at the use-case + e2e levels
exercise end-to-end with the real LLM.

Spec: `2026-05-listing-search-structured-extraction` §4.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from listings.adapters.ai.langchain_query_extractor import (
    LangChainQueryExtractor,
    _ExtractorResult,
)
from listings.domain.models import Typology
from listings.domain.parsed_query import ParsedQuery
from listings.domain.poi_category import PoiCategory


def _make(*, returns=None, side_effect=None, timeout_seconds=4.0):
    svc = LangChainQueryExtractor(
        model="gpt-4o-mini",
        openai_api_key="test-key",
        timeout_seconds=timeout_seconds,
        max_output_tokens=200,
    )
    svc._llm = AsyncMock()
    if side_effect is not None:
        svc._llm.ainvoke = AsyncMock(side_effect=side_effect)
    else:
        svc._llm.ainvoke = AsyncMock(return_value=returns)
    return svc


class TestEnvelopeMapping:
    async def test_full_payload_round_trips_to_parsedquery(self):
        envelope = _ExtractorResult(
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
            nearby_pois=[PoiCategory.SCHOOL, PoiCategory.GYM],
        )
        svc = _make(returns=envelope)
        parsed = await svc.extract("anything")
        assert isinstance(parsed, ParsedQuery)
        assert parsed.typology == Typology.HOUSE
        assert parsed.min_bedrooms == 3
        assert parsed.min_price == Decimal("250000")
        assert parsed.has_pool is True
        # Critical: list → tuple conversion happens at the boundary.
        assert parsed.nearby_pois == (PoiCategory.SCHOOL, PoiCategory.GYM)
        assert isinstance(parsed.nearby_pois, tuple)

    async def test_empty_envelope_yields_default_parsedquery(self):
        svc = _make(returns=_ExtractorResult())
        parsed = await svc.extract("anything")
        assert parsed.free_text_remainder == ""
        assert parsed.typology is None
        assert parsed.nearby_pois == ()


class TestFailurePaths:
    async def test_timeout_raises(self):
        async def slow_ainvoke(*_a, **_kw):
            await asyncio.sleep(10)

        svc = _make(side_effect=slow_ainvoke, timeout_seconds=0.01)
        with pytest.raises(asyncio.TimeoutError):
            await svc.extract("anything")

    async def test_llm_error_bubbles(self):
        svc = _make(side_effect=RuntimeError("rate limit"))
        with pytest.raises(RuntimeError, match="rate limit"):
            await svc.extract("anything")
