"""Unit tests for `InMemoryPropertyListingRepository`.

Focus areas (same idempotency semantics as the SQLAlchemy adapter):
- `upsert_from_event` inserts the first row from a carried-state payload
- Subsequent higher-version upsert updates the row
- Lower/equal-version upsert is idempotency-dropped (returns None,
  stored row unchanged)
- Price snapshot picks the minimum amount
- First image with display_order == 0 populates `first_image_s3_key`
- `delete_if_newer` respects the version guard
- `update_location` patches parish/municipality/district + bumps
  `location_enrichment_attempts`
- `increment_enrichment_attempts` bumps without setting
  `location_enriched_at`
"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from listings.adapters.inmemory.inmemory_property_listing_repo import (
    InMemoryPropertyListingRepository,
)


@pytest.fixture
def repo():
    return InMemoryPropertyListingRepository()


def _event(
    *,
    id_: str | None = None,
    version: int = 1,
    status: str = "active",
    address: str = "Some Address",
    prices=None,
    images=None,
    characteristics=None,
) -> dict:
    return {
        "id": id_ or str(uuid4()),
        "organization_id": str(uuid4()),
        "aggregate_version": version,
        "address": address,
        "listing_type": "sale",
        "typology": "apartment",
        "status": status,
        "description": None,
        "latitude": None,
        "longitude": None,
        "characteristics": characteristics,
        "prices": prices or [],
        "images": images or [],
    }


async def test_first_upsert_inserts_row(repo):
    event = _event(address="Arca, Ponte de Lima, Viana do Castelo")
    row = await repo.upsert_from_event(
        event_data=event, source_occurred_at=datetime.now(timezone.utc)
    )
    assert row is not None
    assert row.source_aggregate_version == 1
    assert row.parish is None  # enrichment hasn't run yet
    assert row.location_enrichment_attempts == 0


async def test_higher_version_upsert_updates(repo):
    pid = str(uuid4())
    await repo.upsert_from_event(
        event_data=_event(id_=pid, version=1, address="v1"),
        source_occurred_at=datetime.now(timezone.utc),
    )
    row2 = await repo.upsert_from_event(
        event_data=_event(id_=pid, version=2, address="v2"),
        source_occurred_at=datetime.now(timezone.utc),
    )
    assert row2.source_aggregate_version == 2


async def test_lower_or_equal_version_is_idempotency_dropped(repo):
    pid = str(uuid4())
    await repo.upsert_from_event(
        event_data=_event(id_=pid, version=5, address="v5"),
        source_occurred_at=datetime.now(timezone.utc),
    )
    # Equal version — drop
    result = await repo.upsert_from_event(
        event_data=_event(id_=pid, version=5, address="trying to overwrite"),
        source_occurred_at=datetime.now(timezone.utc),
    )
    assert result is None
    # Lower version — drop
    result2 = await repo.upsert_from_event(
        event_data=_event(id_=pid, version=3, address="even older"),
        source_occurred_at=datetime.now(timezone.utc),
    )
    assert result2 is None


async def test_min_price_picks_lowest_across_prices(repo):
    event = _event(
        prices=[
            {"amount": "350000.00", "listing_type": "sale"},
            {"amount": "280000.00", "listing_type": "sale"},
            {"amount": "400000.00", "listing_type": "sale"},
        ],
    )
    row = await repo.upsert_from_event(
        event_data=event, source_occurred_at=datetime.now(timezone.utc)
    )
    assert row.min_price == Decimal("280000.00")


async def test_first_image_uses_display_order_zero(repo):
    event = _event(
        images=[
            {"id": str(uuid4()), "s3_key": "p/ordered-2.jpg", "display_order": 2},
            {"id": str(uuid4()), "s3_key": "p/thumb.jpg", "display_order": 0},
            {"id": str(uuid4()), "s3_key": "p/ordered-1.jpg", "display_order": 1},
        ],
    )
    row = await repo.upsert_from_event(
        event_data=event, source_occurred_at=datetime.now(timezone.utc)
    )
    assert row.first_image_s3_key == "p/thumb.jpg"


async def test_first_image_falls_back_to_first_when_no_order_zero(repo):
    event = _event(
        images=[
            {"id": str(uuid4()), "s3_key": "p/a.jpg", "display_order": 1},
            {"id": str(uuid4()), "s3_key": "p/b.jpg", "display_order": 2},
        ],
    )
    row = await repo.upsert_from_event(
        event_data=event, source_occurred_at=datetime.now(timezone.utc)
    )
    assert row.first_image_s3_key == "p/a.jpg"


async def test_characteristics_denormalised(repo):
    event = _event(
        characteristics={
            "num_of_bedrooms": 3,
            "num_of_bathrooms": 2,
            "area_in_m2": 120.5,
            "has_pool": True,
            "has_garden": False,
            "has_elevator": None,
        },
    )
    row = await repo.upsert_from_event(
        event_data=event, source_occurred_at=datetime.now(timezone.utc)
    )
    assert row.num_of_bedrooms == 3
    assert row.num_of_bathrooms == 2
    assert row.area_in_m2 == 120  # coerced to int
    assert row.has_pool is True
    assert row.has_garden is False
    assert row.has_elevator is None


async def test_delete_if_newer_drops_on_older_version(repo):
    from uuid import UUID

    pid = str(uuid4())
    await repo.upsert_from_event(
        event_data=_event(id_=pid, version=5),
        source_occurred_at=datetime.now(timezone.utc),
    )
    # Delete with version 5 — same as current, should drop
    result = await repo.delete_if_newer(
        property_id=UUID(pid),
        source_aggregate_version=5,
        source_occurred_at=datetime.now(timezone.utc),
    )
    assert result is False
    assert await repo.get_by_id(UUID(pid)) is not None


async def test_delete_if_newer_succeeds_on_higher_version(repo):
    from uuid import UUID

    pid = str(uuid4())
    await repo.upsert_from_event(
        event_data=_event(id_=pid, version=5),
        source_occurred_at=datetime.now(timezone.utc),
    )
    result = await repo.delete_if_newer(
        property_id=UUID(pid),
        source_aggregate_version=6,
        source_occurred_at=datetime.now(timezone.utc),
    )
    assert result is True
    assert await repo.get_by_id(UUID(pid)) is None


async def test_update_location_patches_and_bumps_attempts(repo):
    from uuid import UUID

    pid = str(uuid4())
    await repo.upsert_from_event(
        event_data=_event(id_=pid, version=1, address="Arca, Ponte de Lima, Viana"),
        source_occurred_at=datetime.now(timezone.utc),
    )
    from listings.application.ports.address_searcher import ParsedAddress

    updated = await repo.update_location(
        property_id=UUID(pid),
        parsed=ParsedAddress(
            country="Portugal",
            parish="Arca",
            municipality="Ponte de Lima",
            district="Viana do Castelo",
        ),
    )
    assert updated.parish == "Arca"
    assert updated.municipality == "Ponte de Lima"
    assert updated.district == "Viana do Castelo"
    assert updated.location_enriched_at is not None
    assert updated.location_enrichment_attempts == 1


async def test_increment_enrichment_attempts_bumps_only_counter(repo):
    from uuid import UUID

    pid = str(uuid4())
    await repo.upsert_from_event(
        event_data=_event(id_=pid, version=1),
        source_occurred_at=datetime.now(timezone.utc),
    )
    bumped = await repo.increment_enrichment_attempts(property_id=UUID(pid))
    assert bumped.location_enrichment_attempts == 1
    assert bumped.location_enriched_at is None  # not set by this method


async def test_get_by_id_returns_none_for_unknown(repo):
    from uuid import UUID

    assert await repo.get_by_id(UUID(str(uuid4()))) is None
