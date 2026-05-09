"""OpenAI embedding adapter.

Wraps `openai.AsyncOpenAI.embeddings.create`. ADR-013 §6 / spec
`2026-05-listing-semantic-search`. The model is injected at
construction time so the adapter doesn't have to know the env layout
— the container reads `EMBEDDING_MODEL` and passes it down.
"""

from __future__ import annotations

from openai import AsyncOpenAI

from listings.application.ports.embedding_provider import EmbeddingProvider


class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def embed(self, text: str) -> list[float]:
        response = await self._client.embeddings.create(
            model=self._model,
            input=text,
        )
        return list(response.data[0].embedding)
