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
    PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT_V1,
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


async def test_property_created_upserts_and_emits_enrichment(context, repo, publisher):
    data = _snapshot()
    event = DomainEvent(event_type=PROPERTY_CREATED_V1, data=data)
    await handle_property_event(event, context)

    row = await repo.get_by_id(UUID(data["id"]))
    assert row is not None
    assert row.address == data["address"]
    assert len(publisher.published) == 1
    emitted = publisher.published[0]
    assert emitted.event_type == PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT_V1
    assert emitted.data == {"property_id": data["id"], "address": data["address"]}


async def test_property_updated_upserts_and_emits_enrichment(context, repo, publisher):
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
    assert row.address == "new address"
    assert len(publisher.published) == 1
    assert publisher.published[0].data["address"] == "new address"


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
    assert row.address == "v5"
    assert publisher.published == []


async def test_property_deleted_removes_row_and_skips_enrichment(context, repo, publisher):
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
    # DELETED events don't emit enrichment — the row is gone.
    assert publisher.published == []


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
