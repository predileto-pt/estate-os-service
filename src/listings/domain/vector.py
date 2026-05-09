"""Value types for the `VectorIndex` port.

Provider-neutral shapes — every adapter (in-memory, Pinecone v1,
turbopuffer/pgvector/Qdrant/Weaviate as future swaps) must accept and
emit these. ADR-013 §6.

`VectorFilter`: a dict where each key maps to an operator dict.
Operators recognized at the port surface: `eq`, `in`, `gte`, `lte`.
Composition via the special `"and"` key holding a list of sub-filters.
Adapters MAY support more internally; the port surface stays at this
minimum so handlers + use cases never branch on the wired adapter.

Examples:

    {"status": {"eq": "ACTIVE"}}
    {"municipality": {"in": ["lisboa", "porto"]}}
    {"price_eur": {"gte": 100000, "lte": 500000}}
    {"and": [
        {"status": {"eq": "ACTIVE"}},
        {"price_eur": {"gte": 100000}},
    ]}
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

VectorFilter = dict[str, Any]


@dataclass(frozen=True)
class VectorMatch:
    """One ANN hit returned by `VectorIndex.query`."""

    id: str
    score: float
    metadata: dict[str, Any]
