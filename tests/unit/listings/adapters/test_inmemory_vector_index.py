"""Contract tests for `InMemoryVectorIndex`.

These tests double as the contract test the Pinecone adapter must
also pass — when the Pinecone adapter lands in a follow-up commit,
these are parametrized over both adapters.
"""

from __future__ import annotations

import pytest

from listings.adapters.vector.inmemory_index import InMemoryVectorIndex

NAMESPACE = "test-ns-v1"


def _vec(dim: int = 4, seed: float = 1.0) -> list[float]:
    return [seed * (i + 1) for i in range(dim)]


async def test_upsert_then_query_returns_match():
    idx = InMemoryVectorIndex()
    await idx.upsert(
        vector_id="a",
        vector=_vec(),
        metadata={"status": "ACTIVE", "municipality": "lisboa"},
        namespace=NAMESPACE,
    )
    matches = await idx.query(
        vector=_vec(), filter={"status": {"eq": "ACTIVE"}}, top_k=10, namespace=NAMESPACE
    )
    assert len(matches) == 1
    assert matches[0].id == "a"
    assert matches[0].metadata["municipality"] == "lisboa"


async def test_upsert_overwrites_existing_id():
    idx = InMemoryVectorIndex()
    await idx.upsert(
        vector_id="a",
        vector=[1.0, 0.0, 0.0, 0.0],
        metadata={"status": "DRAFT"},
        namespace=NAMESPACE,
    )
    await idx.upsert(
        vector_id="a",
        vector=[0.0, 1.0, 0.0, 0.0],
        metadata={"status": "ACTIVE"},
        namespace=NAMESPACE,
    )
    matches = await idx.query(
        vector=[0.0, 1.0, 0.0, 0.0],
        filter={"status": {"eq": "ACTIVE"}},
        top_k=10,
        namespace=NAMESPACE,
    )
    assert len(matches) == 1
    assert matches[0].id == "a"


async def test_delete_removes_vector():
    idx = InMemoryVectorIndex()
    await idx.upsert(
        vector_id="a", vector=_vec(), metadata={"status": "ACTIVE"}, namespace=NAMESPACE
    )
    await idx.delete(vector_id="a", namespace=NAMESPACE)
    matches = await idx.query(
        vector=_vec(), filter={"status": {"eq": "ACTIVE"}}, top_k=10, namespace=NAMESPACE
    )
    assert matches == []


async def test_delete_missing_id_is_noop():
    idx = InMemoryVectorIndex()
    await idx.delete(vector_id="nope", namespace=NAMESPACE)  # must not raise


async def test_update_metadata_merges_keys():
    idx = InMemoryVectorIndex()
    await idx.upsert(
        vector_id="a",
        vector=_vec(),
        metadata={"status": "ACTIVE", "price_eur": 100000},
        namespace=NAMESPACE,
    )
    await idx.update_metadata(vector_id="a", metadata={"status": "WITHDRAWN"}, namespace=NAMESPACE)
    matches = await idx.query(
        vector=_vec(),
        filter={"status": {"eq": "WITHDRAWN"}},
        top_k=10,
        namespace=NAMESPACE,
    )
    assert len(matches) == 1
    # Untouched key still there
    assert matches[0].metadata["price_eur"] == 100000


async def test_filter_eq():
    idx = InMemoryVectorIndex()
    for vid, status in [("a", "ACTIVE"), ("b", "WITHDRAWN")]:
        await idx.upsert(
            vector_id=vid,
            vector=_vec(),
            metadata={"status": status},
            namespace=NAMESPACE,
        )
    matches = await idx.query(
        vector=_vec(), filter={"status": {"eq": "ACTIVE"}}, top_k=10, namespace=NAMESPACE
    )
    assert {m.id for m in matches} == {"a"}


async def test_filter_in():
    idx = InMemoryVectorIndex()
    for vid, mun in [("a", "lisboa"), ("b", "porto"), ("c", "braga")]:
        await idx.upsert(
            vector_id=vid,
            vector=_vec(),
            metadata={"municipality": mun},
            namespace=NAMESPACE,
        )
    matches = await idx.query(
        vector=_vec(),
        filter={"municipality": {"in": ["lisboa", "porto"]}},
        top_k=10,
        namespace=NAMESPACE,
    )
    assert {m.id for m in matches} == {"a", "b"}


async def test_filter_gte_lte_range():
    idx = InMemoryVectorIndex()
    for vid, price in [("a", 50000), ("b", 200000), ("c", 600000)]:
        await idx.upsert(
            vector_id=vid,
            vector=_vec(),
            metadata={"price_eur": price},
            namespace=NAMESPACE,
        )
    matches = await idx.query(
        vector=_vec(),
        filter={"price_eur": {"gte": 100000, "lte": 500000}},
        top_k=10,
        namespace=NAMESPACE,
    )
    assert {m.id for m in matches} == {"b"}


async def test_filter_and_composition():
    idx = InMemoryVectorIndex()
    rows = [
        ("a", "ACTIVE", "lisboa", 200000),
        ("b", "ACTIVE", "porto", 150000),
        ("c", "WITHDRAWN", "lisboa", 200000),
    ]
    for vid, status, mun, price in rows:
        await idx.upsert(
            vector_id=vid,
            vector=_vec(),
            metadata={"status": status, "municipality": mun, "price_eur": price},
            namespace=NAMESPACE,
        )
    matches = await idx.query(
        vector=_vec(),
        filter={
            "and": [
                {"status": {"eq": "ACTIVE"}},
                {"municipality": {"in": ["lisboa", "porto"]}},
                {"price_eur": {"gte": 100000}},
            ]
        },
        top_k=10,
        namespace=NAMESPACE,
    )
    assert {m.id for m in matches} == {"a", "b"}


async def test_top_k_caps_results():
    idx = InMemoryVectorIndex()
    for i in range(10):
        await idx.upsert(
            vector_id=f"id-{i}",
            vector=_vec(seed=i + 1.0),
            metadata={"status": "ACTIVE"},
            namespace=NAMESPACE,
        )
    matches = await idx.query(
        vector=_vec(seed=1.0),
        filter={"status": {"eq": "ACTIVE"}},
        top_k=3,
        namespace=NAMESPACE,
    )
    assert len(matches) == 3


async def test_query_results_sorted_by_score_desc():
    idx = InMemoryVectorIndex()
    # Upsert vectors at known angles relative to a query vector
    await idx.upsert(vector_id="aligned", vector=[1.0, 0.0], metadata={}, namespace=NAMESPACE)
    await idx.upsert(vector_id="orthogonal", vector=[0.0, 1.0], metadata={}, namespace=NAMESPACE)
    await idx.upsert(vector_id="antiparallel", vector=[-1.0, 0.0], metadata={}, namespace=NAMESPACE)
    matches = await idx.query(vector=[1.0, 0.0], filter={}, top_k=10, namespace=NAMESPACE)
    assert [m.id for m in matches] == ["aligned", "orthogonal", "antiparallel"]
    assert matches[0].score > matches[1].score > matches[2].score


async def test_namespaces_are_isolated():
    idx = InMemoryVectorIndex()
    await idx.upsert(
        vector_id="a",
        vector=_vec(),
        metadata={"status": "ACTIVE"},
        namespace="ns-1",
    )
    matches_other = await idx.query(vector=_vec(), filter={}, top_k=10, namespace="ns-2")
    assert matches_other == []


async def test_unsupported_filter_operator_raises():
    idx = InMemoryVectorIndex()
    await idx.upsert(vector_id="a", vector=_vec(), metadata={"x": 1}, namespace=NAMESPACE)
    with pytest.raises(ValueError):
        await idx.query(
            vector=_vec(),
            filter={"x": {"contains": 1}},  # unsupported
            top_k=10,
            namespace=NAMESPACE,
        )
