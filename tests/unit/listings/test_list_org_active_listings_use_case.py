"""Unit tests for `ListOrgActiveListings`.

Status-exclusion is intentionally not asserted here — the in-memory
adapter cannot filter by status (`ListedProperty` has no `status`
field). The SQL `WHERE status = ACTIVE` predicate is the canonical
enforcement; see the spec §"Status filtering" for context.
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from listings.adapters.inmemory.inmemory_listing_repository import InMemoryListingRepository
from listings.application.ports.listing_repository import PropertyFilters
from listings.application.use_cases.list_org_active_listings import ListOrgActiveListings
from listings.domain.models import ListedProperty, ListingType, Typology

ORG_A = UUID("00000000-0000-0000-0000-000000000001")
ORG_B = UUID("00000000-0000-0000-0000-000000000002")


def _listed(*, organization_id: UUID = ORG_A, address: str = "Rua A") -> ListedProperty:
    now = datetime.now(timezone.utc)
    return ListedProperty(
        id=uuid4(),
        organization_id=organization_id,
        address=address,
        listing_type=ListingType.SALE,
        typology=Typology.APARTMENT,
        description=None,
        characteristics=None,
        latitude=None,
        longitude=None,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def repo() -> InMemoryListingRepository:
    return InMemoryListingRepository()


@pytest.fixture
def filters() -> PropertyFilters:
    return PropertyFilters()


async def test_empty_repo_returns_empty_and_zero(repo, filters):
    use_case = ListOrgActiveListings(listing_repo=repo)
    properties, total = await use_case.execute(organization_id=ORG_A, filters=filters)
    assert properties == []
    assert total == 0


async def test_returns_only_calling_org_rows(repo, filters):
    a1 = _listed(organization_id=ORG_A, address="Org A — 1")
    a2 = _listed(organization_id=ORG_A, address="Org A — 2")
    b1 = _listed(organization_id=ORG_B, address="Org B — 1")
    repo.add(a1)
    repo.add(a2)
    repo.add(b1)

    use_case = ListOrgActiveListings(listing_repo=repo)
    properties, total = await use_case.execute(organization_id=ORG_A, filters=filters)

    addresses = {p.address for p in properties}
    assert addresses == {"Org A — 1", "Org A — 2"}
    assert total == 2


async def test_passes_organization_id_and_filters_to_repo(filters):
    """Tracking-repo subclass: assert the use case calls the port with the
    exact arguments we passed in (no mutation, no skipping count)."""

    class TrackingRepo(InMemoryListingRepository):
        def __init__(self) -> None:
            super().__init__()
            self.list_calls: list[tuple[UUID, PropertyFilters]] = []
            self.count_calls: list[tuple[UUID, PropertyFilters]] = []

        async def list_active_for_organization(self, organization_id, filters):
            self.list_calls.append((organization_id, filters))
            return await super().list_active_for_organization(organization_id, filters)

        async def count_active_for_organization(self, organization_id, filters):
            self.count_calls.append((organization_id, filters))
            return await super().count_active_for_organization(organization_id, filters)

    repo = TrackingRepo()
    custom_filters = PropertyFilters(
        listing_type=ListingType.SALE,
        typology=Typology.APARTMENT,
        limit=5,
        offset=10,
    )

    use_case = ListOrgActiveListings(listing_repo=repo)
    await use_case.execute(organization_id=ORG_A, filters=custom_filters)

    # The use case forwards the call exactly once for list and once for count,
    # both with the org_id + filters as-passed. (The in-memory `count` impl
    # internally calls `list` again with limit=999999 — that's adapter detail,
    # so we check only the first invocation of list.)
    assert repo.list_calls[0] == (ORG_A, custom_filters)
    assert repo.count_calls == [(ORG_A, custom_filters)]


async def test_total_reflects_unpaginated_count(repo):
    """`total` is the full count for the org, not the paginated page size."""
    for i in range(5):
        repo.add(_listed(organization_id=ORG_A, address=f"Row {i}"))

    use_case = ListOrgActiveListings(listing_repo=repo)
    properties, total = await use_case.execute(
        organization_id=ORG_A,
        filters=PropertyFilters(limit=2, offset=0),
    )

    assert len(properties) == 2
    assert total == 5
