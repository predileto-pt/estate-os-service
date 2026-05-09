"""Unit tests for the listings projector `handle_property_event`.

Covers the three event types (CREATED / UPDATED / DELETED), the
idempotency-drop fan-out skip, and the enrichment-publish side effect.
"""

from uuid import UUID, uuid4

import pytest

from listings.adapters.inmemory.inmemory_property_listing_repo import (
    InMemoryPropertyListingRepository,
)
from listings.adapters.workers.property_event_handler import handle_property_event
from shared.events.base import DomainEvent
from shared.events.types import (
    PROPERTY_CREATED_V1,
    PROPERTY_DELETED_V1,
    PROPERTY_LISTING_DELETED_V1,
    PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT_V1,
    PROPERTY_LISTING_UPDATED_V1,
    PROPERTY_PUBLISHED_V1,
    PROPERTY_UPDATED_V1,
)


class _RecordingPublisher:
    def __init__(self):
        self.published: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.published.append(event)


@pytest.fixture
def repo():
    return InMemoryPropertyListingRepository()


@pytest.fixture
def publisher():
    return _RecordingPublisher()


@pytest.fixture
def context(repo, publisher):
    class _Listings:
        pass

    listings = _Listings()
    listings.property_listing_repo = repo
    return {"listings": listings, "publisher": publisher}


def _snapshot(
    *, id_: str | None = None, version: int = 1, address: str = "Arca, Ponte de Lima, Viana"
) -> dict:
    return {
        "id": id_ or str(uuid4()),
        "organization_id": str(uuid4()),
        "aggregate_version": version,
        "address": address,
        "listing_type": "sale",
        "typology": "apartment",
        "status": "active",
        "description": None,
        "latitude": None,
        "longitude": None,
        "characteristics": None,
        "prices": [],
        "images": [],
    }


async def test_property_created_upserts_and_fans_out(context, repo, publisher):
    data = _snapshot()
    event = DomainEvent(event_type=PROPERTY_CREATED_V1, data=data)
    await handle_property_event(event, context)

    row = await repo.get_by_id(UUID(data["id"]))
    assert row is not None
    types = [e.event_type for e in publisher.published]
    # Two listings-internal events fan out: address-enrichment + embedding.
    assert PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT_V1 in types
    assert PROPERTY_LISTING_UPDATED_V1 in types
    enrich = next(
        e
        for e in publisher.published
        if e.event_type == PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT_V1
    )
    # Enrichment payload now carries postal_code + country (spec
    # 2026-05-property-address-enrichment-fix). The upstream snapshot
    # in this test has no postal_code in the address, so it's None;
    # country defaults to 'Portugal' for legacy events.
    assert enrich.data == {
        "property_id": data["id"],
        "address": data["address"],
        "postal_code": None,
        "country": "Portugal",
    }
    embed = next(e for e in publisher.published if e.event_type == PROPERTY_LISTING_UPDATED_V1)
    assert embed.data == {"property_id": data["id"]}


async def test_property_updated_upserts_and_fans_out(context, repo, publisher):
    pid = str(uuid4())
    # Seed a v1 row
    await handle_property_event(
        DomainEvent(event_type=PROPERTY_CREATED_V1, data=_snapshot(id_=pid, version=1)),
        context,
    )
    publisher.published.clear()

    updated_data = _snapshot(id_=pid, version=2, address="new address")
    await handle_property_event(
        DomainEvent(event_type=PROPERTY_UPDATED_V1, data=updated_data),
        context,
    )

    row = await repo.get_by_id(UUID(pid))
    assert row.source_aggregate_version == 2
    types = [e.event_type for e in publisher.published]
    assert PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT_V1 in types
    assert PROPERTY_LISTING_UPDATED_V1 in types


async def test_older_update_is_dropped_and_no_enrichment_emitted(context, repo, publisher):
    pid = str(uuid4())
    # Seed v5
    await handle_property_event(
        DomainEvent(
            event_type=PROPERTY_CREATED_V1, data=_snapshot(id_=pid, version=5, address="v5")
        ),
        context,
    )
    publisher.published.clear()

    # Replay v3 — should be idempotency-dropped AND no enrichment published
    await handle_property_event(
        DomainEvent(
            event_type=PROPERTY_UPDATED_V1,
            data=_snapshot(id_=pid, version=3, address="older"),
        ),
        context,
    )

    row = await repo.get_by_id(UUID(pid))
    assert row.source_aggregate_version == 5
    assert publisher.published == []


async def test_property_deleted_removes_row_and_emits_listing_deleted(context, repo, publisher):
    pid = str(uuid4())
    await handle_property_event(
        DomainEvent(event_type=PROPERTY_CREATED_V1, data=_snapshot(id_=pid, version=1)),
        context,
    )
    publisher.published.clear()

    await handle_property_event(
        DomainEvent(
            event_type=PROPERTY_DELETED_V1,
            data={
                "id": pid,
                "organization_id": str(uuid4()),
                "aggregate_version": 2,
            },
        ),
        context,
    )

    assert await repo.get_by_id(UUID(pid)) is None
    # DELETED events skip the enrichment fan-out (no row to enrich) but
    # do publish PROPERTY_LISTING_DELETED.v1 so the embedding handler
    # removes the vector from the index.
    types = [e.event_type for e in publisher.published]
    assert PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT_V1 not in types
    assert PROPERTY_LISTING_DELETED_V1 in types
    deleted = next(e for e in publisher.published if e.event_type == PROPERTY_LISTING_DELETED_V1)
    assert deleted.data == {"property_id": pid}


async def test_delete_older_than_stored_drops(context, repo):
    pid = str(uuid4())
    await handle_property_event(
        DomainEvent(event_type=PROPERTY_CREATED_V1, data=_snapshot(id_=pid, version=5)),
        context,
    )

    await handle_property_event(
        DomainEvent(
            event_type=PROPERTY_DELETED_V1,
            data={
                "id": pid,
                "organization_id": str(uuid4()),
                "aggregate_version": 3,  # older
            },
        ),
        context,
    )

    # Row still there
    assert await repo.get_by_id(UUID(pid)) is not None


async def test_property_published_upserts_active_and_fans_out(context, repo, publisher):
    """PROPERTY_PUBLISHED.v1 has the same carried-state shape as UPDATED,
    so the projector upserts it via the same path. The snapshot carries
    status='active' (set by Property.publish()), which is what the public
    portal's `WHERE status = ACTIVE` filter keys on."""
    pid = str(uuid4())
    # Seed a DRAFT row via CREATED first
    draft_snapshot = _snapshot(id_=pid, version=1)
    draft_snapshot["status"] = "draft"
    await handle_property_event(
        DomainEvent(event_type=PROPERTY_CREATED_V1, data=draft_snapshot),
        context,
    )
    publisher.published.clear()

    # Now publish — status flips to active, version bumps to 2
    published_snapshot = _snapshot(id_=pid, version=2)
    assert published_snapshot["status"] == "active"
    await handle_property_event(
        DomainEvent(event_type=PROPERTY_PUBLISHED_V1, data=published_snapshot),
        context,
    )

    row = await repo.get_by_id(UUID(pid))
    assert row is not None
    assert row.source_aggregate_version == 2
    # status column is populated from the snapshot
    assert row.status.value == "active"
    # Both fan-out events fire — same pre-existing behavior as UPDATED.
    types = [e.event_type for e in publisher.published]
    assert PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT_V1 in types
    assert PROPERTY_LISTING_UPDATED_V1 in types


async def test_older_published_is_dropped(context, repo, publisher):
    """Idempotency guard applies to PROPERTY_PUBLISHED.v1 exactly like
    CREATED/UPDATED — replaying an older publish event must not regress
    the row."""
    pid = str(uuid4())
    # Seed v5 with address "v5-addr"
    await handle_property_event(
        DomainEvent(
            event_type=PROPERTY_UPDATED_V1, data=_snapshot(id_=pid, version=5, address="v5-addr")
        ),
        context,
    )
    publisher.published.clear()

    # Replay an old v3 PUBLISHED — must be dropped
    old_published = _snapshot(id_=pid, version=3, address="old-addr")
    await handle_property_event(
        DomainEvent(event_type=PROPERTY_PUBLISHED_V1, data=old_published),
        context,
    )

    row = await repo.get_by_id(UUID(pid))
    assert row.source_aggregate_version == 5
    assert publisher.published == []


async def test_handler_without_publisher_in_context_does_not_raise(repo):
    """The projector must work even if no publisher is available
    (e.g., a minimal test context). Enrichment fan-out is just skipped.
    """

    class _Listings:
        pass

    listings = _Listings()
    listings.property_listing_repo = repo
    context_no_pub = {"listings": listings}  # no 'publisher' key

    data = _snapshot()
    await handle_property_event(
        DomainEvent(event_type=PROPERTY_CREATED_V1, data=data), context_no_pub
    )
    row = await repo.get_by_id(UUID(data["id"]))
    assert row is not None


# Helper: allow passing UUID from string in tests.
def _as_uuid(s: str) -> UUID:
    return UUID(s)
