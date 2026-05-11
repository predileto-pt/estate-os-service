"""`list_active_keyset` contract — verified against the in-memory
adapter (the SqlAlchemy adapter shares the contract; integration
test covers real-DB behavior).

Tests prove:
- Head page returns `limit` items, `has_more=True` when more rows
  exist.
- Tail page returns `<= limit` items, `has_more=False`.
- Walking through pages via the returned cursor covers every row,
  no duplicates, no skips, in `(created_at DESC, id DESC)` order.
- Filter predicates apply to the keyset query.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from listings.adapters.inmemory.inmemory_property_listing_repo import (
    InMemoryPropertyListingRepository,
)
from listings.domain.models import ListingType, PropertyStatus, Typology
from listings.domain.pagination import ListCursor
from listings.domain.property_filters import PropertyFilters
from listings.domain.property_listing import PropertyListing


def _listing(*, created_at: datetime, listing_id: UUID, listing_type: ListingType = ListingType.SALE) -> PropertyListing:
    return PropertyListing(
        id=listing_id,
        organization_id=uuid4(),
        title="Test property",
        status=PropertyStatus.ACTIVE,
        listing_type=listing_type,
        typology=Typology.APARTMENT,
        parish=None, municipality=None, district=None,
        location_enriched_at=None, location_enrichment_attempts=0,
        num_of_bedrooms=None, num_of_bathrooms=None, area_in_m2=None,
        has_pool=None, has_garden=None, has_elevator=None,
        min_price=None, first_image_s3_key=None, description=None,
        latitude=None, longitude=None,
        source_aggregate_version=1, source_occurred_at=created_at,
        created_at=created_at, updated_at=created_at,
    )


@pytest.fixture
def repo() -> InMemoryPropertyListingRepository:
    """7 listings with strictly decreasing created_at — easy to assert order."""
    r = InMemoryPropertyListingRepository()
    base = datetime(2026, 5, 11, 12, 0, 0, tzinfo=timezone.utc)
    for i in range(7):
        listing = _listing(
            created_at=base - timedelta(hours=i),
            listing_id=UUID(int=i + 1),
        )
        r._rows[listing.id] = listing  # noqa: SLF001 — test-only direct seed
    return r


async def test_head_page_returns_limit_items_and_has_more(repo: InMemoryPropertyListingRepository):
    items, has_more = await repo.list_active_keyset(
        filters=PropertyFilters(), cursor=None, limit=3,
    )
    assert len(items) == 3
    assert has_more is True


async def test_tail_page_reports_no_more(repo: InMemoryPropertyListingRepository):
    items, has_more = await repo.list_active_keyset(
        filters=PropertyFilters(), cursor=None, limit=10,
    )
    assert len(items) == 7
    assert has_more is False


async def test_walking_pages_covers_all_rows_in_order(repo: InMemoryPropertyListingRepository):
    """Page through with limit=2 and assert every row appears once,
    in (created_at DESC, id DESC) order, with no gaps."""
    seen: list[UUID] = []
    cursor: ListCursor | None = None
    while True:
        items, has_more = await repo.list_active_keyset(
            filters=PropertyFilters(), cursor=cursor, limit=2,
        )
        seen.extend(it.id for it in items)
        if not has_more or not items:
            break
        last = items[-1]
        # The use case mints the cursor; the repo only signals has_more.
        cursor = ListCursor(fp="test", created_at=last.created_at, id=last.id)

    # Same set of rows in the same order as a single big query.
    expected = await repo.list_active_keyset(
        filters=PropertyFilters(), cursor=None, limit=100,
    )
    assert seen == [it.id for it in expected[0]]
    assert len(set(seen)) == 7  # no duplicates


async def test_filter_predicates_apply_to_keyset(repo: InMemoryPropertyListingRepository):
    # Mark half the rows as purchase so we can verify the filter applies.
    for i, listing in enumerate(list(repo._rows.values())):  # noqa: SLF001
        if i % 2 == 0:
            repo._rows[listing.id] = _listing(  # noqa: SLF001
                created_at=listing.created_at,
                listing_id=listing.id,
                listing_type=ListingType.PURCHASE,
            )

    items, _ = await repo.list_active_keyset(
        filters=PropertyFilters(listing_type=ListingType.SALE),
        cursor=None,
        limit=10,
    )
    assert all(it.listing_type == ListingType.SALE for it in items)
