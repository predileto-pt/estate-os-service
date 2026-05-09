"""`VectorIndex` port — provider-neutral vector store.

Adapters: in-memory (tests + local dev), Pinecone (v1 production),
turbopuffer / pgvector / Qdrant / Weaviate (future swaps). ADR-013 §6.

Every operation takes a `namespace` string. Namespace = embedding
model version (e.g. `openai-text-embedding-3-small-v1`). A model bump
means: build the new namespace from scratch via a backfill, validate
offline, atomically flip the `VECTOR_INDEX_NAMESPACE` config, drop
the old namespace.

The vector ID is the listings `property_listing_id` (UUID stringified)
— one listing → one vector. Idempotent upserts; deletes by ID.
"""

from __future__ import annotations

from typing import Protocol

from listings.domain.vector import VectorFilter, VectorMatch


class VectorIndex(Protocol):
    async def upsert(
        self,
        *,
        vector_id: str,
        vector: list[float],
        metadata: dict,
        namespace: str,
    ) -> None: ...

    async def delete(self, *, vector_id: str, namespace: str) -> None: ...

    async def update_metadata(
        self,
        *,
        vector_id: str,
        metadata: dict,
        namespace: str,
    ) -> None: ...

    async def query(
        self,
        *,
        vector: list[float],
        filter: VectorFilter,
        top_k: int,
        namespace: str,
    ) -> list[VectorMatch]: ...
