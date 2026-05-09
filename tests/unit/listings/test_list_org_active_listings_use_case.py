"""Unit tests for `ListOrgActiveListings`.

Migrated from the legacy `ListingRepository` (read mapping over the
live `properties` table) to `PropertyListingRepository` (carried-state
projection). Status filtering is now native to the projection — the
row carries `status` as a column.
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from listings.adapters.inmemory.inmemory_property_listing_repo import (
    InMemoryPropertyListingRepository,
)
from listings.application.use_cases.list_org_active_listings import ListOrgActiveListings
from listings.domain.property_filters import PropertyFilters
from listings.domain.property_listing import PropertyListing

ORG_A = UUID("00000000-0000-0000-0000-000000000001")
ORG_B = UUID("00000000-0000-0000-0000-000000000002")


async def _seed(
    repo: InMemoryPropertyListingRepository,
    *,
    organization_id: UUID = ORG_A,
    description: str = "row",
    status: str = "active",
    listing_type: str = "sale",
    typology: str = "apartment",
    version: int = 1,
) -> PropertyListing:
    """Drop a row directly via the InMemory upsert so we don't have to
    mount the projector for every test."""
    snapshot = {
        "id": str(uuid4()),
        "organization_id": str(organization_id),
        "aggregate_version": version,
        "address": "Rua A, Lisboa",
        "listing_type": listing_type,
        "typology": typology,
        "status": status,
        "description": description,
        "latitude": None,
        "longitude": None,
        "characteristics": None,
        "prices": [],
        "images": [],
    }
    row = await repo.upsert_from_event(
        event_data=snapshot,
        source_occurred_at=datetime(2026, 5, 9, 12, 0, 0, tzinfo=timezone.utc),
    )
    assert row is not None
    return row


@pytest.fixture
def repo() -> InMemoryPropertyListingRepository:
    return InMemoryPropertyListingRepository()


@pytest.fixture
def filters() -> PropertyFilters:
    return PropertyFilters()


async def test_empty_repo_returns_empty_and_zero(repo, filters):
    use_case = ListOrgActiveListings(property_listing_repo=repo)
    properties, total = await use_case.execute(organization_id=ORG_A, filters=filters)
    assert properties == []
    assert total == 0


async def test_returns_only_calling_org_rows(repo, filters):
    await _seed(repo, organization_id=ORG_A, description="Org A — 1")
    await _seed(repo, organization_id=ORG_A, description="Org A — 2")
    await _seed(repo, organization_id=ORG_B, description="Org B — 1")

    use_case = ListOrgActiveListings(property_listing_repo=repo)
    properties, total = await use_case.execute(organization_id=ORG_A, filters=filters)

    descriptions = {p.description for p in properties}
    assert descriptions == {"Org A — 1", "Org A — 2"}
    assert total == 2


async def test_excludes_non_active_rows(repo, filters):
    """Status filtering is enforced by the projection-side adapter
    (the row's `status` column is a real value). Non-ACTIVE rows
    should be excluded from the org list."""
    await _seed(repo, organization_id=ORG_A, description="active 1", status="active")
    await _seed(repo, organization_id=ORG_A, description="draft 1", status="draft")
    await _seed(repo, organization_id=ORG_A, description="sold 1", status="sold")

    use_case = ListOrgActiveListings(property_listing_repo=repo)
    properties, total = await use_case.execute(organization_id=ORG_A, filters=filters)

    descriptions = {p.description for p in properties}
    assert descriptions == {"active 1"}
    assert total == 1


async def test_total_reflects_unpaginated_count(repo):
    for i in range(5):
        await _seed(repo, organization_id=ORG_A, description=f"Row {i}")

    use_case = ListOrgActiveListings(property_listing_repo=repo)
    properties, total = await use_case.execute(
        organization_id=ORG_A,
        filters=PropertyFilters(limit=2, offset=0),
    )

    assert len(properties) == 2
    assert total == 5
