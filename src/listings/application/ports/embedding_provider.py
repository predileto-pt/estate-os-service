"""`EmbeddingProvider` port — text → dense vector.

Adapters: stub (deterministic, for tests + local dev) and OpenAI v1.
ADR-013 §6.
"""

from __future__ import annotations

from typing import Protocol


class EmbeddingProvider(Protocol):
    async def embed(self, text: str) -> list[float]: ...
