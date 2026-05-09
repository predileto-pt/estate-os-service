"""Deterministic stub `EmbeddingProvider` for tests + local dev.

Derives a unit vector from SHA-256(text). Same text → same vector,
byte-for-byte; different text → different vector. NOT semantically
meaningful — never use this in production. Local `docker compose up`
uses this when no `OPENAI_API_KEY` is wired so the listings worker
runs without external API calls.
"""

from __future__ import annotations

import hashlib
import math
import random

from listings.application.ports.embedding_provider import EmbeddingProvider


class StubEmbeddingProvider(EmbeddingProvider):
    def __init__(self, dimensions: int = 1536) -> None:
        self.dimensions = dimensions

    async def embed(self, text: str) -> list[float]:
        seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16)
        rng = random.Random(seed)
        values = [rng.uniform(-1.0, 1.0) for _ in range(self.dimensions)]
        norm = math.sqrt(sum(v * v for v in values))
        if norm == 0:
            return values
        return [v / norm for v in values]
