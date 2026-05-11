"""ListLocations use-case unit tests.

Covers:
- Hierarchical grouping (district → municipality → parish)
- Alphabetical ordering at each level (case-insensitive)
- Triples with NULL district are dropped from the tree
- Triples with NULL parish still contribute their municipality
- Empty DB returns `LocationTree(districts=[])`
- TTL cache: second request inside the window doesn't hit the repo

Spec: `2026-05-listing-semantic-search-read-path` §Test strategy.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from listings.adapters.inmemory.inmemory_property_listing_repo import (
    InMemoryPropertyListingRepository,
)
from listings.application.use_cases.list_locations import ListLocations


async def _seed(repo, *, parish=None, municipality=None, district=None, status="active"):
    from listings.application.ports.address_searcher import ParsedAddress

    pid = str(uuid4())
    await repo.upsert_from_event(
        event_data={
            "id": pid,
            "organization_id": str(uuid4()),
            "aggregate_version": 1,
            "address": "x",
            "listing_type": "sale",
            "typology": "apartment",
            "status": status,
            "description": None,
            "latitude": None,
            "longitude": None,
            "characteristics": None,
            "prices": [],
            "images": [],
        },
        source_occurred_at=datetime.now(timezone.utc),
    )
    if any(v is not None for v in (parish, municipality, district)):
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


@pytest.fixture
def repo():
    return InMemoryPropertyListingRepository()


class TestShape:
    async def test_groups_into_hierarchical_tree(self, repo):
        await _seed(repo, parish="Cascais", municipality="Cascais", district="Lisboa")
        await _seed(repo, parish="Estoril", municipality="Cascais", district="Lisboa")
        await _seed(repo, parish="Belém", municipality="Lisboa", district="Lisboa")
        await _seed(repo, parish="Foz", municipality="Porto", district="Porto")

        uc = ListLocations(property_listing_repo=repo, ttl_seconds=300)
        tree = await uc.execute()

        # Two districts, alphabetical
        assert [d.name for d in tree.districts] == ["Lisboa", "Porto"]
        lisboa = tree.districts[0]
        assert [m.name for m in lisboa.municipalities] == ["Cascais", "Lisboa"]
        assert lisboa.municipalities[0].parishes == ["Cascais", "Estoril"]
        assert lisboa.municipalities[1].parishes == ["Belém"]
        porto = tree.districts[1]
        assert [m.name for m in porto.municipalities] == ["Porto"]

    async def test_alphabetical_ordering_is_case_insensitive(self, repo):
        await _seed(repo, parish="apple", municipality="banana", district="cherry")
        await _seed(repo, parish="Apple Inn", municipality="Banana Plus", district="Cherry Tree")

        uc = ListLocations(property_listing_repo=repo, ttl_seconds=300)
        tree = await uc.execute()

        names = [d.name for d in tree.districts]
        assert names == sorted(names, key=str.casefold)

    async def test_null_district_excluded_from_tree(self, repo):
        # Only parish + municipality enriched — no district anchor.
        await _seed(repo, parish="Foo", municipality="Bar", district=None)
        await _seed(repo, parish="Belém", municipality="Lisboa", district="Lisboa")

        uc = ListLocations(property_listing_repo=repo, ttl_seconds=300)
        tree = await uc.execute()

        assert [d.name for d in tree.districts] == ["Lisboa"]

    async def test_null_parish_still_contributes_municipality(self, repo):
        await _seed(repo, parish=None, municipality="Cascais", district="Lisboa")
        await _seed(repo, parish="Estoril", municipality="Cascais", district="Lisboa")

        uc = ListLocations(property_listing_repo=repo, ttl_seconds=300)
        tree = await uc.execute()

        cascais = tree.districts[0].municipalities[0]
        assert cascais.name == "Cascais"
        # Only the non-None parish surfaces.
        assert cascais.parishes == ["Estoril"]

    async def test_non_active_rows_excluded(self, repo):
        await _seed(
            repo,
            parish="Belém",
            municipality="Lisboa",
            district="Lisboa",
            status="draft",
        )

        uc = ListLocations(property_listing_repo=repo, ttl_seconds=300)
        tree = await uc.execute()
        assert tree.districts == []

    async def test_empty_db_returns_empty_tree(self, repo):
        uc = ListLocations(property_listing_repo=repo, ttl_seconds=300)
        tree = await uc.execute()
        assert tree.districts == []


class TestCache:
    async def test_second_request_within_ttl_uses_cache(self, repo):
        await _seed(repo, parish="Cascais", municipality="Cascais", district="Lisboa")

        repo_calls = {"count": 0}
        real_list = repo.list_locations

        async def counted_list():
            repo_calls["count"] += 1
            return await real_list()

        repo.list_locations = counted_list  # type: ignore[assignment]

        clock_now = [1000.0]
        uc = ListLocations(
            property_listing_repo=repo,
            ttl_seconds=300,
            clock=lambda: clock_now[0],
        )

        await uc.execute()
        await uc.execute()
        clock_now[0] = 1100.0  # 100s later — still inside TTL
        await uc.execute()

        assert repo_calls["count"] == 1  # Only the first call hit the repo.

    async def test_request_after_ttl_refreshes(self, repo):
        await _seed(repo, parish="Cascais", municipality="Cascais", district="Lisboa")

        repo_calls = {"count": 0}
        real_list = repo.list_locations

        async def counted_list():
            repo_calls["count"] += 1
            return await real_list()

        repo.list_locations = counted_list  # type: ignore[assignment]

        clock_now = [1000.0]
        uc = ListLocations(
            property_listing_repo=repo,
            ttl_seconds=300,
            clock=lambda: clock_now[0],
        )

        await uc.execute()
        clock_now[0] = 1301.0  # 301s later — past TTL
        await uc.execute()

        assert repo_calls["count"] == 2

    async def test_cache_returns_same_object(self, repo):
        await _seed(repo, parish="Cascais", municipality="Cascais", district="Lisboa")

        clock_now = [1000.0]
        uc = ListLocations(
            property_listing_repo=repo,
            ttl_seconds=300,
            clock=lambda: clock_now[0],
        )
        a = await uc.execute()
        b = await uc.execute()
        # Same frozen LocationTree instance.
        assert a is b
