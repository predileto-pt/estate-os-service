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


# ──────────── Search read path (hydrate + /locations) ────────────


async def _seed(repo, *, pid: str, status: str = "active", **kw):
    """Seed a row, then optionally enrich its location."""
    parish = kw.pop("parish", None)
    municipality = kw.pop("municipality", None)
    district = kw.pop("district", None)
    await repo.upsert_from_event(
        event_data=_event(id_=pid, status=status, **kw),
        source_occurred_at=datetime.now(timezone.utc),
    )
    if any(v is not None for v in (parish, municipality, district)):
        from listings.application.ports.address_searcher import ParsedAddress
        from uuid import UUID as _UUID

        await repo.update_location(
            property_id=_UUID(pid),
            parsed=ParsedAddress(
                country="Portugal",
                parish=parish,
                municipality=municipality,
                district=district,
            ),
        )


class TestListByIds:
    async def test_returns_active_rows_matching_ids(self, repo):
        from uuid import UUID

        a, b, c = str(uuid4()), str(uuid4()), str(uuid4())
        await _seed(repo, pid=a)
        await _seed(repo, pid=b)
        await _seed(repo, pid=c)
        rows = await repo.list_by_ids([UUID(a), UUID(c)])
        assert {str(r.id) for r in rows} == {a, c}

    async def test_excludes_non_active_rows(self, repo):
        from uuid import UUID

        active_id = str(uuid4())
        draft_id = str(uuid4())
        await _seed(repo, pid=active_id, status="active")
        await _seed(repo, pid=draft_id, status="draft")
        rows = await repo.list_by_ids([UUID(active_id), UUID(draft_id)])
        assert {str(r.id) for r in rows} == {active_id}

    async def test_empty_ids_short_circuits(self, repo):
        assert await repo.list_by_ids([]) == []

    async def test_unknown_ids_return_empty(self, repo):
        from uuid import UUID

        assert await repo.list_by_ids([UUID(str(uuid4()))]) == []


class TestListLocations:
    async def test_distinct_triples_from_enriched_rows(self, repo):
        for parish, municipality, district in [
            ("Cascais", "Cascais", "Lisboa"),
            ("Cascais", "Cascais", "Lisboa"),  # duplicate
            ("Estoril", "Cascais", "Lisboa"),
            ("Belém", "Lisboa", "Lisboa"),
        ]:
            await _seed(
                repo,
                pid=str(uuid4()),
                parish=parish,
                municipality=municipality,
                district=district,
            )
        triples = await repo.list_locations()
        # Three distinct triples; ordering is unspecified.
        as_tuples = {(t.parish, t.municipality, t.district) for t in triples}
        assert as_tuples == {
            ("Cascais", "Cascais", "Lisboa"),
            ("Estoril", "Cascais", "Lisboa"),
            ("Belém", "Lisboa", "Lisboa"),
        }

    async def test_excludes_rows_with_no_location_columns(self, repo):
        # No enrichment → all three columns are None → excluded.
        await _seed(repo, pid=str(uuid4()))
        await _seed(
            repo,
            pid=str(uuid4()),
            parish="Cascais",
            municipality="Cascais",
            district="Lisboa",
        )
        triples = await repo.list_locations()
        assert {(t.parish, t.municipality, t.district) for t in triples} == {
            ("Cascais", "Cascais", "Lisboa")
        }

    async def test_excludes_non_active_rows(self, repo):
        await _seed(
            repo,
            pid=str(uuid4()),
            status="draft",
            parish="Cascais",
            municipality="Cascais",
            district="Lisboa",
        )
        assert await repo.list_locations() == []

    async def test_empty_repo_returns_empty(self, repo):
        assert await repo.list_locations() == []
