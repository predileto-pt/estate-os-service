"""Pinecone v1 adapter for `VectorIndex`.

Translates the provider-neutral filter operators (`eq`, `in`, `gte`,
`lte`, `and`) to Pinecone's Mongo-style filter syntax. Vector ID is
the `property_listing_id`; namespace is the embedding model version.
ADR-013 §4.

Connection model: a single `PineconeAsyncio` client + a single
`AsyncIndex` handle reused for the worker's lifetime.

Index handle resolution:
- If `host` is provided, the handle is constructed synchronously via
  `pc.IndexAsyncio(host=...)` — no startup RTT to the control plane.
  This is the preferred wiring; pass the host string from the
  Pinecone dashboard (or `pc index describe`).
- If only `index_name` is provided, the handle is resolved lazily on
  first use via `await pc.index(name=...)`, which triggers a
  `describe_index` lookup. One-time cost at startup; the SDK caches
  the resolved host.

We don't `close()` the client — process exit cleans up.
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
    def __init__(
        self,
        *,
        api_key: str,
        host: str | None = None,
        index_name: str | None = None,
    ) -> None:
        if not host and not index_name:
            raise ValueError("PineconeVectorIndex requires either host (preferred) or index_name")
        self._client = PineconeAsyncio(api_key=api_key)
        self._host = host
        self._index_name = index_name
        self._index: Any | None = None

    async def _get_index(self) -> Any:
        if self._index is not None:
            return self._index
        if self._host:
            # Sync construction — no control-plane RTT.
            self._index = self._client.IndexAsyncio(host=self._host)
        else:
            # Lazy describe-index lookup; SDK caches the resolved host.
            self._index = await self._client.index(name=self._index_name or "")
        return self._index

    async def upsert(
        self,
        *,
        vector_id: str,
        vector: list[float],
        metadata: dict,
        namespace: str,
    ) -> None:
        idx = await self._get_index()
        await idx.upsert(
            vectors=[{"id": vector_id, "values": vector, "metadata": metadata}],
            namespace=namespace,
        )

    async def delete(self, *, vector_id: str, namespace: str) -> None:
        idx = await self._get_index()
        await idx.delete(ids=[vector_id], namespace=namespace)

    async def update_metadata(
        self,
        *,
        vector_id: str,
        metadata: dict,
        namespace: str,
    ) -> None:
        idx = await self._get_index()
        await idx.update(
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
        idx = await self._get_index()
        translated = _translate_filter(filter) if filter else None
        response = await idx.query(
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
