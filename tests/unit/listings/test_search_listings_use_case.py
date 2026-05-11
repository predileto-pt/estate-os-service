"""SearchListings use-case unit tests.

Covers every fail-open branch + `_build_filter` translation. Stubs
the three external ports (`QueryUnderstandingService`,
`EmbeddingProvider`, `VectorIndex`) and uses the real
`InMemoryPropertyListingRepository` for the hydrate step.

Spec: `2026-05-listing-semantic-search-read-path` §Test strategy.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from listings.adapters.inmemory.inmemory_property_listing_repo import (
    InMemoryPropertyListingRepository,
)
from listings.application.use_cases.search_listings import SearchListings
from listings.domain.location_filter import LocationFilter
from listings.domain.models import ListingType, PropertyStatus, Typology
from listings.domain.property_filters import PropertyFilters
from listings.domain.vector import VectorMatch

NAMESPACE = "test-namespace-v1"
TOP_K = 50


# ──────────── Stubs ────────────


class _StubQU:
    def __init__(self, *, returns: str | None = None, raises: Exception | None = None):
        self.returns = returns
        self.raises = raises
        self.called_with: list[str] = []

    async def rewrite(self, query: str) -> str:
        self.called_with.append(query)
        if self.raises is not None:
            raise self.raises
        return self.returns if self.returns is not None else query


class _StubEmbed:
    def __init__(self, *, returns: list[float] | None = None, raises: Exception | None = None):
        self.returns = returns or [0.1, 0.2, 0.3]
        self.raises = raises
        self.called_with: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.called_with.append(text)
        if self.raises is not None:
            raise self.raises
        return list(self.returns)


class _StubVectorIndex:
    def __init__(
        self,
        *,
        returns: list[VectorMatch] | None = None,
        raises: Exception | None = None,
    ):
        self.returns = returns or []
        self.raises = raises
        self.last_filter: dict | None = None
        self.last_top_k: int | None = None
        self.last_namespace: str | None = None

    async def upsert(self, **_kw) -> None:
        return None

    async def delete(self, **_kw) -> None:
        return None

    async def update_metadata(self, **_kw) -> None:
        return None

    async def query(self, *, vector, filter, top_k, namespace):
        self.last_filter = filter
        self.last_top_k = top_k
        self.last_namespace = namespace
        if self.raises is not None:
            raise self.raises
        return list(self.returns)


# ──────────── Fixtures ────────────


async def _seed_active(repo, *, parish: str, municipality: str, district: str) -> str:
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
            "status": "active",
            "description": "desc",
            "latitude": None,
            "longitude": None,
            "characteristics": None,
            "prices": [],
            "images": [],
        },
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


@pytest.fixture
def repo():
    return InMemoryPropertyListingRepository()


# ──────────── Happy path ────────────


class TestHappyPath:
    async def test_returns_rows_in_score_order(self, repo):
        a = await _seed_active(repo, parish="Cascais", municipality="Cascais", district="Lisboa")
        b = await _seed_active(repo, parish="Cascais", municipality="Cascais", district="Lisboa")
        c = await _seed_active(repo, parish="Cascais", municipality="Cascais", district="Lisboa")

        # b > a > c in score order
        matches = [
            VectorMatch(id=b, score=0.9, metadata={}),
            VectorMatch(id=a, score=0.7, metadata={}),
            VectorMatch(id=c, score=0.4, metadata={}),
        ]

        uc = SearchListings(
            query_understanding=_StubQU(returns="rewritten q"),
            embedding_provider=_StubEmbed(),
            vector_index=_StubVectorIndex(returns=matches),
            property_listing_repo=repo,
            namespace=NAMESPACE,
            top_k=TOP_K,
        )

        rows, total = await uc.execute(
            query="casa com piscina",
            location=LocationFilter(parish="Cascais"),
            filters=PropertyFilters(limit=10, offset=0),
        )

        assert [str(r.id) for r in rows] == [b, a, c]
        assert total == 3

    async def test_pagination_applies_over_ranked_list(self, repo):
        ids = [
            await _seed_active(repo, parish="Cascais", municipality="Cascais", district="Lisboa")
            for _ in range(5)
        ]
        matches = [VectorMatch(id=ids[i], score=1.0 - i * 0.1, metadata={}) for i in range(5)]

        uc = SearchListings(
            query_understanding=_StubQU(),
            embedding_provider=_StubEmbed(),
            vector_index=_StubVectorIndex(returns=matches),
            property_listing_repo=repo,
            namespace=NAMESPACE,
            top_k=TOP_K,
        )

        page1, total1 = await uc.execute(
            query="x",
            location=LocationFilter(parish="Cascais"),
            filters=PropertyFilters(limit=2, offset=0),
        )
        assert [str(r.id) for r in page1] == [ids[0], ids[1]]
        assert total1 == 5

        page2, total2 = await uc.execute(
            query="x",
            location=LocationFilter(parish="Cascais"),
            filters=PropertyFilters(limit=2, offset=2),
        )
        assert [str(r.id) for r in page2] == [ids[2], ids[3]]
        assert total2 == 5

    async def test_top_k_bounded_by_limit_plus_offset(self, repo):
        """`top_k = min(self._top_k, limit + offset)` — request top-k
        should never exceed the user's window."""
        # Seed nothing — we only care about the top_k passed to the index.
        vi = _StubVectorIndex(returns=[])
        uc = SearchListings(
            query_understanding=_StubQU(),
            embedding_provider=_StubEmbed(),
            vector_index=vi,
            property_listing_repo=repo,
            namespace=NAMESPACE,
            top_k=50,
        )
        await uc.execute(
            query="x",
            location=LocationFilter(parish="Cascais"),
            filters=PropertyFilters(limit=3, offset=7),
        )
        assert vi.last_top_k == 10

    async def test_top_k_capped_by_vector_index_top_k(self, repo):
        vi = _StubVectorIndex(returns=[])
        uc = SearchListings(
            query_understanding=_StubQU(),
            embedding_provider=_StubEmbed(),
            vector_index=vi,
            property_listing_repo=repo,
            namespace=NAMESPACE,
            top_k=10,
        )
        await uc.execute(
            query="x",
            location=LocationFilter(parish="Cascais"),
            filters=PropertyFilters(limit=20, offset=999),
        )
        assert vi.last_top_k == 10

    async def test_namespace_threaded_through(self, repo):
        vi = _StubVectorIndex(returns=[])
        uc = SearchListings(
            query_understanding=_StubQU(),
            embedding_provider=_StubEmbed(),
            vector_index=vi,
            property_listing_repo=repo,
            namespace="custom-ns-v2",
            top_k=TOP_K,
        )
        await uc.execute(
            query="x",
            location=LocationFilter(parish="Cascais"),
            filters=PropertyFilters(limit=5, offset=0),
        )
        assert vi.last_namespace == "custom-ns-v2"

    async def test_rewritten_query_is_what_gets_embedded(self, repo):
        embed = _StubEmbed()
        uc = SearchListings(
            query_understanding=_StubQU(returns="rewritten form"),
            embedding_provider=embed,
            vector_index=_StubVectorIndex(returns=[]),
            property_listing_repo=repo,
            namespace=NAMESPACE,
            top_k=TOP_K,
        )
        await uc.execute(
            query="raw user query",
            location=LocationFilter(parish="Cascais"),
            filters=PropertyFilters(limit=5, offset=0),
        )
        assert embed.called_with == ["rewritten form"]

    async def test_empty_matches_returns_empty(self, repo):
        await _seed_active(repo, parish="Cascais", municipality="Cascais", district="Lisboa")
        uc = SearchListings(
            query_understanding=_StubQU(),
            embedding_provider=_StubEmbed(),
            vector_index=_StubVectorIndex(returns=[]),
            property_listing_repo=repo,
            namespace=NAMESPACE,
            top_k=TOP_K,
        )
        rows, total = await uc.execute(
            query="x",
            location=LocationFilter(parish="Cascais"),
            filters=PropertyFilters(limit=10, offset=0),
        )
        assert rows == []
        assert total == 0

    async def test_stale_vector_dropped_by_active_filter(self, repo):
        """A match id for a now-WITHDRAWN listing is dropped at hydrate
        — the in-memory `list_by_ids` filters to ACTIVE."""
        a = await _seed_active(repo, parish="Cascais", municipality="Cascais", district="Lisboa")
        b = await _seed_active(repo, parish="Cascais", municipality="Cascais", district="Lisboa")
        # Flip `b` to draft so it's no longer ACTIVE.
        repo._rows[UUID(b)].status = PropertyStatus.DRAFT  # type: ignore[attr-defined]

        matches = [
            VectorMatch(id=b, score=0.9, metadata={}),  # stale — should be dropped
            VectorMatch(id=a, score=0.7, metadata={}),
        ]
        uc = SearchListings(
            query_understanding=_StubQU(),
            embedding_provider=_StubEmbed(),
            vector_index=_StubVectorIndex(returns=matches),
            property_listing_repo=repo,
            namespace=NAMESPACE,
            top_k=TOP_K,
        )
        rows, total = await uc.execute(
            query="x",
            location=LocationFilter(parish="Cascais"),
            filters=PropertyFilters(limit=10, offset=0),
        )
        assert [str(r.id) for r in rows] == [a]
        # total reflects post-hydrate count, not Pinecone's count
        assert total == 1


# ──────────── Fail-open branches ────────────


class TestFailOpen:
    async def test_rewrite_failure_embeds_raw_query(self, repo):
        await _seed_active(repo, parish="Cascais", municipality="Cascais", district="Lisboa")
        embed = _StubEmbed()
        uc = SearchListings(
            query_understanding=_StubQU(raises=RuntimeError("LLM timeout")),
            embedding_provider=embed,
            vector_index=_StubVectorIndex(returns=[]),
            property_listing_repo=repo,
            namespace=NAMESPACE,
            top_k=TOP_K,
        )
        await uc.execute(
            query="raw user query",
            location=LocationFilter(parish="Cascais"),
            filters=PropertyFilters(limit=10, offset=0),
        )
        assert embed.called_with == ["raw user query"]

    async def test_embed_failure_triggers_relational_fallback(self, repo):
        a = await _seed_active(repo, parish="Cascais", municipality="Cascais", district="Lisboa")
        # Seed an out-of-location listing — should NOT appear in the fallback.
        await _seed_active(repo, parish="Lisboa", municipality="Lisboa", district="Lisboa")

        uc = SearchListings(
            query_understanding=_StubQU(),
            embedding_provider=_StubEmbed(raises=RuntimeError("embed boom")),
            vector_index=_StubVectorIndex(returns=[]),
            property_listing_repo=repo,
            namespace=NAMESPACE,
            top_k=TOP_K,
        )
        rows, total = await uc.execute(
            query="anything",
            location=LocationFilter(parish="Cascais"),
            filters=PropertyFilters(limit=10, offset=0),
        )
        assert {str(r.id) for r in rows} == {a}
        assert total == 1

    async def test_vector_query_failure_triggers_relational_fallback(self, repo):
        a = await _seed_active(repo, parish="Cascais", municipality="Cascais", district="Lisboa")

        uc = SearchListings(
            query_understanding=_StubQU(),
            embedding_provider=_StubEmbed(),
            vector_index=_StubVectorIndex(raises=RuntimeError("pinecone unavailable")),
            property_listing_repo=repo,
            namespace=NAMESPACE,
            top_k=TOP_K,
        )
        rows, total = await uc.execute(
            query="anything",
            location=LocationFilter(parish="Cascais"),
            filters=PropertyFilters(limit=10, offset=0),
        )
        assert {str(r.id) for r in rows} == {a}
        assert total == 1


# ──────────── _build_filter translation ────────────


class TestBuildFilter:
    def _filter(self, **kw):
        location = kw.pop("location", LocationFilter(parish="Cascais"))
        filters = kw.pop("filters", PropertyFilters())
        return SearchListings._build_filter(location, filters)

    def test_active_status_always_present(self):
        result = self._filter()
        clauses = result["and"]
        assert {"status": {"eq": "active"}} in clauses

    def test_parish_only_lowercased_and_stripped(self):
        result = self._filter(location=LocationFilter(parish="  CASCAIS  "))
        assert {"parish": {"eq": "cascais"}} in result["and"]
        assert not any("municipality" in c for c in result["and"])
        assert not any("district" in c for c in result["and"])

    def test_municipality_only(self):
        result = self._filter(location=LocationFilter(municipality="Lisboa"))
        assert {"municipality": {"eq": "lisboa"}} in result["and"]

    def test_district_only(self):
        result = self._filter(location=LocationFilter(district="Porto"))
        assert {"district": {"eq": "porto"}} in result["and"]

    def test_narrow_further_all_three_levels(self):
        result = self._filter(
            location=LocationFilter(parish="Estoril", municipality="Cascais", district="Lisboa")
        )
        clauses = result["and"]
        assert {"parish": {"eq": "estoril"}} in clauses
        assert {"municipality": {"eq": "cascais"}} in clauses
        assert {"district": {"eq": "lisboa"}} in clauses

    def test_listing_type_filter(self):
        result = self._filter(filters=PropertyFilters(listing_type=ListingType.SALE))
        assert {"listing_type": {"eq": "sale"}} in result["and"]

    def test_typology_filter(self):
        result = self._filter(filters=PropertyFilters(typology=Typology.APARTMENT))
        assert {"typology": {"eq": "apartment"}} in result["and"]

    def test_min_max_price(self):
        result = self._filter(
            filters=PropertyFilters(min_price=Decimal("100000"), max_price=Decimal("500000"))
        )
        assert {"price_eur": {"gte": 100000.0}} in result["and"]
        assert {"price_eur": {"lte": 500000.0}} in result["and"]

    def test_no_structured_filters_when_unset(self):
        result = self._filter()
        # Status + parish (default fixture) only.
        keys = [next(iter(c.keys())) for c in result["and"]]
        assert "listing_type" not in keys
        assert "typology" not in keys
        assert "price_eur" not in keys
