"""Pinecone v1 adapter for `VectorIndex`.

Translates the provider-neutral filter operators (`eq`, `in`, `gte`,
`lte`, `and`) to Pinecone's Mongo-style filter syntax. Vector ID is
the `property_listing_id`; namespace is the embedding model version.
ADR-013 §4.

Connection model: a single `PineconeAsyncio` client + a single
`AsyncIndex` handle constructed at adapter init and reused for the
worker's lifetime. The Pinecone SDK supports this pattern (it's
not strictly context-manager-only); we don't `close()` the client —
process exit cleans up.
"""

from __future__ import annotations

from typing import Any

from pinecone import PineconeAsyncio

from listings.application.ports.vector_index import VectorIndex
from listings.domain.vector import VectorFilter, VectorMatch


def _translate_filter(flt: VectorFilter) -> dict[str, Any]:
    """Port-shape filter → Pinecone Mongo-style filter.

    Port operators: eq / in / gte / lte / and.
    Pinecone equivalents: bare value / $in / $gte / $lte / $and.
    """
    out: dict[str, Any] = {}
    for key, expr in flt.items():
        if key == "and":
            out["$and"] = [_translate_filter(sub) for sub in expr]
            continue
        if not isinstance(expr, dict):
            raise ValueError(f"Filter for {key!r} must be an operator dict, got {expr!r}")
        translated: dict[str, Any] = {}
        for op, operand in expr.items():
            if op == "eq":
                # Pinecone takes a bare value for equality
                out[key] = operand
            elif op == "in":
                translated["$in"] = operand
            elif op == "gte":
                translated["$gte"] = operand
            elif op == "lte":
                translated["$lte"] = operand
            else:
                raise ValueError(f"Unsupported filter operator: {op!r}")
        if translated:
            # If we already wrote a bare-value `eq`, prefer it; otherwise
            # write the operator dict.
            if key not in out:
                out[key] = translated
    return out


class PineconeVectorIndex(VectorIndex):
    def __init__(self, *, api_key: str, index_name: str) -> None:
        self._client = PineconeAsyncio(api_key=api_key)
        # `index()` returns the per-index handle by name (lazy host
        # resolution). The SDK keeps the handle bound to the client.
        self._index = self._client.IndexAsyncio(host=index_name)

    async def upsert(
        self,
        *,
        vector_id: str,
        vector: list[float],
        metadata: dict,
        namespace: str,
    ) -> None:
        await self._index.upsert(
            vectors=[{"id": vector_id, "values": vector, "metadata": metadata}],
            namespace=namespace,
        )

    async def delete(self, *, vector_id: str, namespace: str) -> None:
        await self._index.delete(ids=[vector_id], namespace=namespace)

    async def update_metadata(
        self,
        *,
        vector_id: str,
        metadata: dict,
        namespace: str,
    ) -> None:
        await self._index.update(
            id=vector_id,
            set_metadata=metadata,
            namespace=namespace,
        )

    async def query(
        self,
        *,
        vector: list[float],
        filter: VectorFilter,
        top_k: int,
        namespace: str,
    ) -> list[VectorMatch]:
        translated = _translate_filter(filter) if filter else None
        response = await self._index.query(
            vector=vector,
            top_k=top_k,
            namespace=namespace,
            filter=translated,
            include_metadata=True,
        )
        matches = response.get("matches") if isinstance(response, dict) else response.matches
        out: list[VectorMatch] = []
        for m in matches or []:
            mid = m["id"] if isinstance(m, dict) else m.id
            score = m["score"] if isinstance(m, dict) else m.score
            md = m.get("metadata") if isinstance(m, dict) else (m.metadata or {})
            out.append(VectorMatch(id=mid, score=float(score), metadata=dict(md or {})))
        return out
