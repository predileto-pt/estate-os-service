"""In-memory `VectorIndex` for tests + local dev.

Brute-force cosine over a Python dict — passes the same contract
tests as the Pinecone adapter (ADR-013 §6). Filter operators
supported: `eq`, `in`, `gte`, `lte`, plus the composition key `and`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from listings.application.ports.vector_index import VectorIndex
from listings.domain.vector import VectorFilter, VectorMatch


@dataclass
class _Record:
    vector: list[float]
    metadata: dict[str, Any]


def _matches_filter(metadata: dict[str, Any], flt: VectorFilter) -> bool:
    """Recursive filter evaluator. The port surface only requires `eq`,
    `in`, `gte`, `lte`, plus `and` composition — all other operators
    raise so wiring bugs surface immediately."""
    for key, expr in flt.items():
        if key == "and":
            if not all(_matches_filter(metadata, sub) for sub in expr):
                return False
            continue
        value = metadata.get(key)
        if not isinstance(expr, dict):
            raise ValueError(f"Filter for {key!r} must be an operator dict, got {expr!r}")
        for op, operand in expr.items():
            if op == "eq":
                if value != operand:
                    return False
            elif op == "in":
                if value not in operand:
                    return False
            elif op == "gte":
                if value is None or value < operand:
                    return False
            elif op == "lte":
                if value is None or value > operand:
                    return False
            else:
                raise ValueError(f"Unsupported filter operator: {op!r}")
    return True


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"vector dims mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class InMemoryVectorIndex(VectorIndex):
    def __init__(self) -> None:
        self._namespaces: dict[str, dict[str, _Record]] = {}

    def _ns(self, namespace: str) -> dict[str, _Record]:
        return self._namespaces.setdefault(namespace, {})

    async def upsert(
        self,
        *,
        vector_id: str,
        vector: list[float],
        metadata: dict,
        namespace: str,
    ) -> None:
        self._ns(namespace)[vector_id] = _Record(vector=list(vector), metadata=dict(metadata))

    async def delete(self, *, vector_id: str, namespace: str) -> None:
        self._ns(namespace).pop(vector_id, None)

    async def update_metadata(
        self,
        *,
        vector_id: str,
        metadata: dict,
        namespace: str,
    ) -> None:
        existing = self._ns(namespace).get(vector_id)
        if existing is None:
            return
        merged = {**existing.metadata, **metadata}
        existing.metadata = merged

    async def query(
        self,
        *,
        vector: list[float],
        filter: VectorFilter,
        top_k: int,
        namespace: str,
    ) -> list[VectorMatch]:
        candidates = [
            (vid, rec)
            for vid, rec in self._ns(namespace).items()
            if _matches_filter(rec.metadata, filter)
        ]
        scored = [
            VectorMatch(id=vid, score=_cosine(vector, rec.vector), metadata=dict(rec.metadata))
            for vid, rec in candidates
        ]
        scored.sort(key=lambda m: m.score, reverse=True)
        return scored[:top_k]
