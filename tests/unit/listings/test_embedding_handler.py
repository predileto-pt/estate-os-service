"""Unit tests for the listings embedding handler.

Covers every branch:
- Gate disabled → no-op (no embed call, no upsert)
- Hash unchanged → metadata path only (update_metadata, no embed)
- Hash changed → embed + upsert + status flips to INDEXED
- FAILED status forces re-embed even if hash matches
- Row deleted between event and handler → graceful return
- Embed failure → status flips to FAILED, exception re-raised
- PROPERTY_LISTING_DELETED.v1 → vector deleted from index
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from listings.adapters.embedding.stub_provider import StubEmbeddingProvider
from listings.adapters.inmemory.inmemory_property_listing_repo import (
    InMemoryPropertyListingRepository,
)
from listings.adapters.vector.inmemory_index import InMemoryVectorIndex
from listings.adapters.workers.embedding_handler import (
    handle_listing_deleted,
    handle_listing_embedding,
)
from shared.events.base import DomainEvent
from shared.events.types import (
    PROPERTY_LISTING_DELETED_V1,
    PROPERTY_LISTING_UPDATED_V1,
)

NAMESPACE = "test-ns-v1"
MODEL_VERSION = "text-embedding-3-small"


def _seed_snapshot(*, id_: str, version: int = 1, **overrides) -> dict:
    base = {
        "id": id_,
        "organization_id": str(uuid4()),
        "aggregate_version": version,
        "address": "Rua Augusta 1, Lisboa",
        "listing_type": "sale",
        "typology": "apartment",
        "status": "active",
        "description": "Top-floor flat",
        "latitude": 38.7,
        "longitude": -9.1,
        "characteristics": {
            "area_in_m2": 85,
            "num_of_bedrooms": 2,
            "num_of_bathrooms": 1,
            "built_at": 2018,
            "energy_rating": "A",
        },
        "prices": [{"amount": "350000.00", "listing_type": "sale"}],
        "images": [],
        "pois": [
            {"category": "school", "name": "Escola X", "distance_meters": 234.0},
        ],
    }
    base.update(overrides)
    return base


@pytest.fixture
def repo():
    return InMemoryPropertyListingRepository()


@pytest.fixture
def vector_index():
    return InMemoryVectorIndex()


class _CountingStub(StubEmbeddingProvider):
    """Stub that counts embed calls so we can assert hash-skip works."""

    def __init__(self, dimensions: int = 64) -> None:
        super().__init__(dimensions=dimensions)
        self.call_count = 0

    async def embed(self, text: str) -> list[float]:
        self.call_count += 1
        return await super().embed(text)


@pytest.fixture
def embedding_provider():
    return _CountingStub()


def _container(repo, embedding_provider=None, vector_index=None, namespace=NAMESPACE):
    class _Listings:
        pass

    listings = _Listings()
    listings.property_listing_repo = repo
    listings.embedding_provider = embedding_provider
    listings.vector_index = vector_index
    listings.vector_index_namespace = namespace
    listings.embedding_model_version = MODEL_VERSION
    return {"listings": listings}


async def _seed_row(repo, *, id_: str, version: int = 1, **overrides):
    """Drop a row directly via the InMemory upsert so we don't have to
    mount the projector for every test."""
    snapshot = _seed_snapshot(id_=id_, version=version, **overrides)
    await repo.upsert_from_event(
        event_data=snapshot,
        source_occurred_at=datetime(2026, 5, 9, 12, 0, 0, tzinfo=timezone.utc),
    )


async def test_gate_disabled_is_noop(repo, embedding_provider, vector_index):
    """Both vector_index and embedding_provider None → no work done."""
    pid = str(uuid4())
    await _seed_row(repo, id_=pid)
    ctx = _container(repo, embedding_provider=None, vector_index=None)
    event = DomainEvent(event_type=PROPERTY_LISTING_UPDATED_V1, data={"property_id": pid})
    await handle_listing_embedding(event, ctx)

    assert embedding_provider.call_count == 0
    matches = await vector_index.query(vector=[0.0] * 64, filter={}, top_k=10, namespace=NAMESPACE)
    assert matches == []
    row = await repo.get_by_id(UUID(pid))
    assert row.embedding_status == "PENDING"


async def test_first_index_embeds_and_upserts(repo, embedding_provider, vector_index):
    pid = str(uuid4())
    await _seed_row(repo, id_=pid)
    ctx = _container(repo, embedding_provider, vector_index)
    event = DomainEvent(event_type=PROPERTY_LISTING_UPDATED_V1, data={"property_id": pid})
    await handle_listing_embedding(event, ctx)

    assert embedding_provider.call_count == 1
    row = await repo.get_by_id(UUID(pid))
    assert row.embedding_status == "INDEXED"
    assert row.embedding_text_hash is not None
    assert row.canonical_text_version == "v1"
    assert row.embedding_model_version == MODEL_VERSION
    assert row.embedded_at is not None
    matches = await vector_index.query(
        vector=[0.0] * 64,
        filter={"listing_id": {"eq": pid}},
        top_k=10,
        namespace=NAMESPACE,
    )
    assert len(matches) == 1
    assert matches[0].id == pid
    # Metadata projection
    md = matches[0].metadata
    assert md["status"] == "active"
    assert md["typology"] == "apartment"
    assert md["price_eur"] == 350000.0


async def test_hash_unchanged_skips_embed_calls_metadata_path(
    repo, embedding_provider, vector_index
):
    """Second event with byte-identical canonical text must skip the
    embed call and only refresh metadata."""
    pid = str(uuid4())
    await _seed_row(repo, id_=pid)
    ctx = _container(repo, embedding_provider, vector_index)

    event = DomainEvent(event_type=PROPERTY_LISTING_UPDATED_V1, data={"property_id": pid})
    await handle_listing_embedding(event, ctx)
    assert embedding_provider.call_count == 1

    # Second invocation with same data
    await handle_listing_embedding(event, ctx)
    assert embedding_provider.call_count == 1  # didn't tick


async def test_text_change_triggers_reembed(repo, embedding_provider, vector_index):
    """Re-projecting with a description change flips the canonical-text
    hash, which should force a re-embed."""
    pid = str(uuid4())
    await _seed_row(repo, id_=pid, version=1)
    ctx = _container(repo, embedding_provider, vector_index)

    event = DomainEvent(event_type=PROPERTY_LISTING_UPDATED_V1, data={"property_id": pid})
    await handle_listing_embedding(event, ctx)
    assert embedding_provider.call_count == 1

    # Update with a different description (later version)
    await _seed_row(repo, id_=pid, version=2, description="completely new copy")
    await handle_listing_embedding(event, ctx)
    assert embedding_provider.call_count == 2

    row = await repo.get_by_id(UUID(pid))
    assert row.embedding_status == "INDEXED"


async def test_failed_status_forces_reembed_on_redrive(repo, embedding_provider, vector_index):
    pid = str(uuid4())
    await _seed_row(repo, id_=pid)
    ctx = _container(repo, embedding_provider, vector_index)

    event = DomainEvent(event_type=PROPERTY_LISTING_UPDATED_V1, data={"property_id": pid})
    await handle_listing_embedding(event, ctx)
    assert embedding_provider.call_count == 1

    # Simulate a transient failure that left the row in FAILED state
    # but with the (now-stale) hash still set.
    await repo.set_embedding_status(property_id=UUID(pid), status="FAILED")

    # Even though canonical text is byte-identical, FAILED forces a
    # retry — `needs_reembed` is true.
    await handle_listing_embedding(event, ctx)
    assert embedding_provider.call_count == 2
    row = await repo.get_by_id(UUID(pid))
    assert row.embedding_status == "INDEXED"


async def test_failure_path_marks_row_failed_and_reraises(repo, vector_index):
    """An EmbeddingProvider that raises must flip embedding_status to
    FAILED and re-raise so SQS redrives."""

    class _BoomProvider:
        async def embed(self, text: str) -> list[float]:
            raise RuntimeError("openai exploded")

    pid = str(uuid4())
    await _seed_row(repo, id_=pid)
    ctx = _container(repo, _BoomProvider(), vector_index)
    event = DomainEvent(event_type=PROPERTY_LISTING_UPDATED_V1, data={"property_id": pid})

    with pytest.raises(RuntimeError, match="openai exploded"):
        await handle_listing_embedding(event, ctx)

    row = await repo.get_by_id(UUID(pid))
    assert row.embedding_status == "FAILED"


async def test_row_missing_is_graceful(repo, embedding_provider, vector_index):
    """If the row was deleted between the projector firing the event
    and the embedding handler running, drop the message quietly."""
    ctx = _container(repo, embedding_provider, vector_index)
    event = DomainEvent(event_type=PROPERTY_LISTING_UPDATED_V1, data={"property_id": str(uuid4())})
    await handle_listing_embedding(event, ctx)
    assert embedding_provider.call_count == 0


async def test_handle_listing_deleted_removes_vector(repo, embedding_provider, vector_index):
    pid = str(uuid4())
    await _seed_row(repo, id_=pid)
    ctx = _container(repo, embedding_provider, vector_index)

    # First index the row
    await handle_listing_embedding(
        DomainEvent(event_type=PROPERTY_LISTING_UPDATED_V1, data={"property_id": pid}),
        ctx,
    )
    matches = await vector_index.query(
        vector=[0.0] * 64,
        filter={"listing_id": {"eq": pid}},
        top_k=10,
        namespace=NAMESPACE,
    )
    assert len(matches) == 1

    # Delete it
    await handle_listing_deleted(
        DomainEvent(event_type=PROPERTY_LISTING_DELETED_V1, data={"property_id": pid}),
        ctx,
    )
    matches = await vector_index.query(
        vector=[0.0] * 64,
        filter={"listing_id": {"eq": pid}},
        top_k=10,
        namespace=NAMESPACE,
    )
    assert matches == []


async def test_handle_listing_deleted_with_gate_off_is_noop(repo):
    """Gate off (vector_index None) must not crash on delete."""
    ctx = _container(repo, embedding_provider=None, vector_index=None)
    await handle_listing_deleted(
        DomainEvent(event_type=PROPERTY_LISTING_DELETED_V1, data={"property_id": str(uuid4())}),
        ctx,
    )
