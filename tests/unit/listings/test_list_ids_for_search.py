"""`list_ids_for_search` SQL pre-filter against the in-memory repo.

Pins the load-bearing behaviors:
- Status filter (only ACTIVE rows surface).
- Location filter (parish/municipality/district exact match).
- Route-param HARD filters (typology, listing_type, min/max price).
- ParsedQuery SOFT-HARD filters (each NULL-admitted: column unset
  on the row → row admitted; column set + fails the criterion →
  row excluded).
- Conflict resolution: route_filters > parsed for the SAME field,
  with `is not None` semantics (Decimal('0') doesn't collapse to
  the extractor value).
- Saturation contract: result with len == limit is the caller's
  signal to switch to broad-mode.

Spec: `2026-05-listing-search-structured-extraction` §6/§8.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from listings.adapters.inmemory.inmemory_property_listing_repo import (
    InMemoryPropertyListingRepository,
)
from listings.application.ports.address_searcher import ParsedAddress
from listings.domain.location_filter import LocationFilter
from listings.domain.models import ListingType, Typology
from listings.domain.parsed_query import ParsedQuery
from listings.domain.property_filters import PropertyFilters


@pytest.fixture
def repo():
    return InMemoryPropertyListingRepository()


def _event(
    *,
    pid: str | None = None,
    status: str = "active",
    typology: str = "apartment",
    listing_type: str = "sale",
    chars: dict | None = None,
    prices: list | None = None,
) -> dict:
    return {
        "id": pid or str(uuid4()),
        "organization_id": str(uuid4()),
        "aggregate_version": 1,
        "address": "x",
        "listing_type": listing_type,
        "typology": typology,
        "status": status,
        "description": None,
        "latitude": None,
        "longitude": None,
        "characteristics": chars,
        "prices": prices or [],
        "images": [],
    }


async def _seed(
    repo,
    *,
    parish: str = "Cascais",
    municipality: str = "Cascais",
    district: str = "Lisboa",
    **event_kw,
) -> str:
    """Seed a listing + run address enrichment so parish/municipality/
    district columns are populated (same as the in-memory repo's
    update_location path)."""
    event = _event(**event_kw)
    pid = event["id"]
    await repo.upsert_from_event(
        event_data=event,
        source_occurred_at=datetime.now(timezone.utc),
    )
    await repo.update_location(
        property_id=UUID(pid),
        parsed=ParsedAddress(
            country="Portugal",
            parish=parish,
            municipality=municipality,
            district=district,
        ),
    )
    return pid


_DEFAULT_LOCATION = LocationFilter(parish="Cascais")


class TestStatusAndLocation:
    async def test_only_active_status_surfaces(self, repo):
        active_id = await _seed(repo, status="active")
        await _seed(repo, status="draft")
        await _seed(repo, status="sold")
        ids = await repo.list_ids_for_search(
            location=_DEFAULT_LOCATION,
            route_filters=PropertyFilters(),
            parsed=ParsedQuery(),
            limit=100,
        )
        assert {str(i) for i in ids} == {active_id}

    async def test_parish_filter_excludes_other_parishes(self, repo):
        cascais_id = await _seed(repo, parish="Cascais")
        await _seed(repo, parish="Estoril")
        ids = await repo.list_ids_for_search(
            location=LocationFilter(parish="Cascais"),
            route_filters=PropertyFilters(),
            parsed=ParsedQuery(),
            limit=100,
        )
        assert {str(i) for i in ids} == {cascais_id}


class TestRouteParamHardFilters:
    async def test_typology_filter(self, repo):
        apartment_id = await _seed(repo, typology="apartment")
        await _seed(repo, typology="house")
        ids = await repo.list_ids_for_search(
            location=_DEFAULT_LOCATION,
            route_filters=PropertyFilters(typology=Typology.APARTMENT),
            parsed=ParsedQuery(),
            limit=100,
        )
        assert {str(i) for i in ids} == {apartment_id}

    async def test_listing_type_filter(self, repo):
        sale_id = await _seed(repo, listing_type="sale")
        await _seed(repo, listing_type="purchase")
        ids = await repo.list_ids_for_search(
            location=_DEFAULT_LOCATION,
            route_filters=PropertyFilters(listing_type=ListingType.SALE),
            parsed=ParsedQuery(),
            limit=100,
        )
        assert {str(i) for i in ids} == {sale_id}

    async def test_price_filter_excludes_strict_misses(self, repo):
        cheap_id = await _seed(repo, prices=[{"amount": "200000", "listing_type": "sale"}])
        await _seed(repo, prices=[{"amount": "800000", "listing_type": "sale"}])
        ids = await repo.list_ids_for_search(
            location=_DEFAULT_LOCATION,
            route_filters=PropertyFilters(max_price=Decimal("500000")),
            parsed=ParsedQuery(),
            limit=100,
        )
        assert {str(i) for i in ids} == {cheap_id}

    async def test_price_zero_route_param_preserved(self, repo):
        """Decimal('0') is falsy — sanity that the implementation
        uses `is not None` semantics, not `or`-truthy-checks."""
        free_id = await _seed(repo, prices=[{"amount": "0", "listing_type": "sale"}])
        await _seed(repo, prices=[{"amount": "100000", "listing_type": "sale"}])
        ids = await repo.list_ids_for_search(
            location=_DEFAULT_LOCATION,
            route_filters=PropertyFilters(max_price=Decimal("0")),
            parsed=ParsedQuery(),
            limit=100,
        )
        # max_price=0 means "at most 0 euros". Only the listing at 0 surfaces.
        assert {str(i) for i in ids} == {free_id}


class TestParsedQuerySoftHard:
    async def test_min_bedrooms_excludes_smaller(self, repo):
        t3_id = await _seed(repo, chars={"num_of_bedrooms": 3})
        await _seed(repo, chars={"num_of_bedrooms": 2})
        ids = await repo.list_ids_for_search(
            location=_DEFAULT_LOCATION,
            route_filters=PropertyFilters(),
            parsed=ParsedQuery(min_bedrooms=3),
            limit=100,
        )
        assert {str(i) for i in ids} == {t3_id}

    async def test_min_bedrooms_admits_null_rows(self, repo):
        """Soft-hard NULL semantics: a row with `num_of_bedrooms IS
        NULL` is ADMITTED by the SQL filter. The use case's
        `_partition_and_rank` pushes it to the bottom of the
        result page later, but it must surface from the SQL filter."""
        t3_id = await _seed(repo, chars={"num_of_bedrooms": 3})
        null_id = await _seed(repo, chars=None)
        ids = await repo.list_ids_for_search(
            location=_DEFAULT_LOCATION,
            route_filters=PropertyFilters(),
            parsed=ParsedQuery(min_bedrooms=3),
            limit=100,
        )
        assert {str(i) for i in ids} == {t3_id, null_id}

    async def test_has_pool_admits_null_excludes_false(self, repo):
        with_pool_id = await _seed(repo, chars={"has_pool": True})
        without_pool_id = await _seed(repo, chars={"has_pool": False})
        null_id = await _seed(repo, chars=None)
        ids = await repo.list_ids_for_search(
            location=_DEFAULT_LOCATION,
            route_filters=PropertyFilters(),
            parsed=ParsedQuery(has_pool=True),
            limit=100,
        )
        assert {str(i) for i in ids} == {with_pool_id, null_id}
        assert without_pool_id not in {str(i) for i in ids}

    async def test_has_parking_derives_from_parking_spaces(self, repo):
        with_parking_id = await _seed(repo, chars={"parking_spaces": 2})
        await _seed(repo, chars={"parking_spaces": 0})
        ids = await repo.list_ids_for_search(
            location=_DEFAULT_LOCATION,
            route_filters=PropertyFilters(),
            parsed=ParsedQuery(has_parking=True),
            limit=100,
        )
        assert with_parking_id in {str(i) for i in ids}

    async def test_area_range(self, repo):
        small = await _seed(repo, chars={"area_in_m2": 80})
        mid = await _seed(repo, chars={"area_in_m2": 150})
        big = await _seed(repo, chars={"area_in_m2": 250})
        ids = await repo.list_ids_for_search(
            location=_DEFAULT_LOCATION,
            route_filters=PropertyFilters(),
            parsed=ParsedQuery(min_area_m2=100, max_area_m2=200),
            limit=100,
        )
        assert {str(i) for i in ids} == {mid}
        assert small not in {str(i) for i in ids}
        assert big not in {str(i) for i in ids}


class TestConflictResolution:
    async def test_route_typology_wins_when_set(self, repo):
        apartment_id = await _seed(repo, typology="apartment")
        await _seed(repo, typology="house")
        ids = await repo.list_ids_for_search(
            location=_DEFAULT_LOCATION,
            route_filters=PropertyFilters(typology=Typology.APARTMENT),
            parsed=ParsedQuery(typology=Typology.HOUSE),  # ← conflicts
            limit=100,
        )
        # Route wins → only apartments surface.
        assert {str(i) for i in ids} == {apartment_id}

    async def test_parsed_typology_applies_when_route_is_none(self, repo):
        await _seed(repo, typology="apartment")
        house_id = await _seed(repo, typology="house")
        ids = await repo.list_ids_for_search(
            location=_DEFAULT_LOCATION,
            route_filters=PropertyFilters(),  # no route typology
            parsed=ParsedQuery(typology=Typology.HOUSE),
            limit=100,
        )
        assert {str(i) for i in ids} == {house_id}

    async def test_route_min_price_wins_when_set(self, repo):
        cheap = await _seed(repo, prices=[{"amount": "100000", "listing_type": "sale"}])
        expensive = await _seed(repo, prices=[{"amount": "500000", "listing_type": "sale"}])
        ids = await repo.list_ids_for_search(
            location=_DEFAULT_LOCATION,
            route_filters=PropertyFilters(min_price=Decimal("400000")),
            parsed=ParsedQuery(min_price=Decimal("50000")),  # conflicts (would admit cheap)
            limit=100,
        )
        # Route wins → only the expensive one surfaces.
        assert {str(i) for i in ids} == {expensive}
        assert cheap not in {str(i) for i in ids}


class TestSaturation:
    async def test_limit_saturates_at_cap(self, repo):
        for _ in range(5):
            await _seed(repo)
        ids = await repo.list_ids_for_search(
            location=_DEFAULT_LOCATION,
            route_filters=PropertyFilters(),
            parsed=ParsedQuery(),
            limit=3,
        )
        assert len(ids) == 3
        # The caller reads len(ids) == limit as "saturated → broad mode."

    async def test_below_limit_returns_all(self, repo):
        for _ in range(3):
            await _seed(repo)
        ids = await repo.list_ids_for_search(
            location=_DEFAULT_LOCATION,
            route_filters=PropertyFilters(),
            parsed=ParsedQuery(),
            limit=10,
        )
        assert len(ids) == 3

    async def test_empty_when_no_match(self, repo):
        ids = await repo.list_ids_for_search(
            location=_DEFAULT_LOCATION,
            route_filters=PropertyFilters(),
            parsed=ParsedQuery(),
            limit=10,
        )
        assert ids == []
