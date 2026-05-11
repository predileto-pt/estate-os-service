"""QueryUnderstandingService adapter tests.

Two adapters:
- `IdentityQueryUnderstandingService` — returns input unchanged
  (also the wired adapter when LISTINGS_SEARCH_ENABLED=false).
- `LangChainQueryUnderstandingService` — LLM-backed; tested with a
  stubbed `_llm.ainvoke` so the prompt + envelope-parsing logic is
  pinned without burning OpenAI quota.

Spec: `2026-05-listing-semantic-search-read-path` §Test strategy.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from listings.adapters.ai.langchain_query_understanding import (
    LangChainQueryUnderstandingService,
    _RewriteResult,
)
from listings.adapters.inmemory.inmemory_query_understanding import (
    IdentityQueryUnderstandingService,
)


class TestIdentityQueryUnderstandingService:
    async def test_returns_input_unchanged(self):
        svc = IdentityQueryUnderstandingService()
        assert await svc.rewrite("casa com piscina") == "casa com piscina"

    async def test_returns_empty_string_unchanged(self):
        svc = IdentityQueryUnderstandingService()
        assert await svc.rewrite("") == ""

    async def test_returns_multiline_unchanged(self):
        svc = IdentityQueryUnderstandingService()
        assert await svc.rewrite("linha 1\nlinha 2") == "linha 1\nlinha 2"


class TestLangChainQueryUnderstandingService:
    """Tests stub `_llm.ainvoke` directly so the test is hermetic.

    We don't try to "test the prompt" — that's an evaluation
    problem, not a unit test. We pin:
    - the envelope-parsing path (parses `_RewriteResult.rewritten`),
    - the timeout path (asyncio.TimeoutError → raised),
    - the general-failure path (raise from LLM → bubbles up).
    """

    def _make(self, ainvoke_result=None, ainvoke_side_effect=None, timeout_seconds=4.0):
        svc = LangChainQueryUnderstandingService(
            model="gpt-4o-mini",
            openai_api_key="test-key",
            timeout_seconds=timeout_seconds,
            max_output_tokens=200,
        )
        # Replace the constructed _llm with an async mock.
        if ainvoke_side_effect is not None:
            svc._llm = AsyncMock()
            svc._llm.ainvoke = AsyncMock(side_effect=ainvoke_side_effect)
        else:
            svc._llm = AsyncMock()
            svc._llm.ainvoke = AsyncMock(return_value=ainvoke_result)
        return svc

    async def test_returns_rewritten_field_from_envelope(self):
        svc = self._make(
            ainvoke_result=_RewriteResult(rewritten="casa com varanda, perto de ginásio")
        )
        assert (
            await svc.rewrite("Uma casa com varanda que tenha uma academia perto")
            == "casa com varanda, perto de ginásio"
        )

    async def test_timeout_raises(self):
        async def slow_invoke(*_args, **_kwargs):
            await asyncio.sleep(10)

        svc = self._make(ainvoke_side_effect=slow_invoke, timeout_seconds=0.01)
        with pytest.raises(asyncio.TimeoutError):
            await svc.rewrite("anything")

    async def test_llm_error_bubbles(self):
        svc = self._make(ainvoke_side_effect=RuntimeError("rate limit"))
        with pytest.raises(RuntimeError, match="rate limit"):
            await svc.rewrite("anything")
