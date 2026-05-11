"""SearchListings use-case unit tests (ADR-014 hybrid retrieval).

The new flow:
1. Extract via QueryExtractor → ParsedQuery (fail-open on error).
2. Parallel asyncio.gather:
   - SQL pre-filter via list_ids_for_search → list[UUID] candidates.
   - Embed the canonical-text-v3-shaped render of ParsedQuery.
   Uses `return_exceptions=True` so per-stage failures fall open.
3. Cardinality-guarded ANN. Normal mode passes candidates as a
   `listing_id IN ...` Pinecone filter. Broad mode (when SQL hit
   the LIMIT) runs a broad query + post-intersect.
4. Hydrate via list_by_ids. Partition matched/partial-data rows.
   Sort by score within each, concatenate, paginate.
5. Return (rows, total, parsed).

Spec: 2026-05-listing-search-structured-extraction §6/§8/§11.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from listings.adapters.inmemory.inmemory_property_listing_repo import (
    InMemoryPropertyListingRepository,
)
from listings.adapters.inmemory.inmemory_search_result_cache import (
    InMemorySearchResultCache,
)
from listings.application.ports.address_searcher import ParsedAddress
from listings.application.use_cases.search_listings import (
    SearchListings,
    _has_unevaluable_criterion,
    _render_query_for_embed,
)
from listings.domain.location_filter import LocationFilter
from listings.domain.models import PropertyStatus, Typology
from listings.domain.pagination import SearchCursor, build_search_cache_key
from listings.domain.parsed_query import ParsedQuery
from listings.domain.poi_category import PoiCategory
from listings.domain.property_filters import PropertyFilters
from listings.domain.vector import VectorMatch

NAMESPACE = "test-namespace-v2"
TOP_K = 50
MAX_CANDIDATES = 1000


# ──────────── Stubs ────────────


class _StubExtractor:
    def __init__(self, *, returns=None, raises=None):
        self.returns = returns
        self.raises = raises
        self.called_with: list[str] = []

    async def extract(self, query: str) -> ParsedQuery:
        self.called_with.append(query)
        if self.raises is not None:
            raise self.raises
        return self.returns if self.returns is not None else ParsedQuery(
            free_text_remainder=query
        )


class _StubEmbed:
    def __init__(self, *, returns=None, raises=None):
        self.returns = returns or [0.1, 0.2, 0.3]
        self.raises = raises
        self.called_with: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.called_with.append(text)
        if self.raises is not None:
            raise self.raises
        return list(self.returns)


class _StubVectorIndex:
    def __init__(self, *, returns=None, raises=None):
        self.returns = returns or []
        self.raises = raises
        self.last_filter = None
        self.last_top_k = None
        self.last_namespace = None

    async def upsert(self, **_kw):
        return None

    async def delete(self, **_kw):
        return None

    async def update_metadata(self, **_kw):
        return None

    async def query(self, *, vector, filter, top_k, namespace):
        self.last_filter = filter
        self.last_top_k = top_k
        self.last_namespace = namespace
        if self.raises is not None:
            raise self.raises
        return list(self.returns)


@pytest.fixture
def repo():
    return InMemoryPropertyListingRepository()


async def _seed(
    repo,
    *,
    parish: str = "Cascais",
    municipality: str = "Cascais",
    district: str = "Lisboa",
    status: str = "active",
    typology: str = "apartment",
    chars: dict | None = None,
    prices: list | None = None,
) -> str:
    pid = str(uuid4())
    await repo.upsert_from_event(
        event_data={
            "id": pid,
            "organization_id": str(uuid4()),
            "aggregate_version": 1,
            "address": "x",
            "listing_type": "sale",
            "typology": typology,
            "status": status,
            "description": "desc",
            "latitude": None,
            "longitude": None,
            "characteristics": chars,
            "prices": prices or [],
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


def _make_uc(
    *,
    repo,
    extractor=None,
    embed=None,
    vector_index=None,
    top_k: int = TOP_K,
    max_candidates: int = MAX_CANDIDATES,
    broad_mode_overshoot: int = 4,
    search_cache: InMemorySearchResultCache | None = None,
) -> SearchListings:
    return SearchListings(
        query_extractor=extractor or _StubExtractor(),
        embedding_provider=embed or _StubEmbed(),
        vector_index=vector_index or _StubVectorIndex(),
        property_listing_repo=repo,
        namespace=NAMESPACE,
        top_k=top_k,
        max_pre_filter_candidates=max_candidates,
        broad_mode_overshoot=broad_mode_overshoot,
        search_cache=search_cache or InMemorySearchResultCache(),
        ttl_seconds=60,
    )


# Legacy-shape adapter: maps the old (rows, total, parsed) return that
# this test file was built around to the new (CachedPage, parsed)
# signature, so existing assertions about `rows` and `total` keep
# working. `total` is read out of the cache the use case just
# populated — `len(CachedSearchResult.ranked_ids)`.
async def _execute(
    uc: SearchListings,
    *,
    query: str,
    location: LocationFilter,
    filters: PropertyFilters,
    fp: str = "testfp00",
):
    limit = filters.limit if filters.limit is not None else 50
    offset = filters.offset if filters.offset is not None else 0
    cursor = SearchCursor(fp=fp, offset=offset) if offset > 0 else None
    page, parsed = await uc.execute(
        fp=fp,
        q=query,
        location=location,
        filters=filters,
        cursor=cursor,
        limit=limit,
    )
    hit = await uc._search_cache.get(build_search_cache_key(fp=fp))  # noqa: SLF001
    total = len(hit.ranked_ids) if hit is not None else 0
    return page.items, total, parsed


# ──────────── Happy path ────────────


class TestHappyPath:
    async def test_normal_mode_uses_listing_id_filter(self, repo):
        pid = await _seed(repo)
        vi = _StubVectorIndex(returns=[VectorMatch(id=pid, score=0.9, metadata={})])
        uc = _make_uc(
            repo=repo,
            extractor=_StubExtractor(returns=ParsedQuery(free_text_remainder="x")),
            vector_index=vi,
        )
        rows, total, parsed = await _execute(uc,
            query="x",
            location=LocationFilter(parish="Cascais"),
            filters=PropertyFilters(limit=10, offset=0),
        )
        assert [str(r.id) for r in rows] == [pid]
        assert total == 1
        assert isinstance(parsed, ParsedQuery)
        # Filter should be AND(status, listing_id.in [...]) — not `id`.
        # Pinecone's `id` field isn't metadata-filterable.
        assert vi.last_filter == {
            "and": [
                {"status": {"eq": "active"}},
                {"listing_id": {"in": [pid]}},
            ]
        }

    async def test_returns_3_tuple_with_parsed(self, repo):
        await _seed(repo)
        uc = _make_uc(
            repo=repo,
            extractor=_StubExtractor(
                returns=ParsedQuery(
                    typology=Typology.APARTMENT, nearby_pois=(PoiCategory.SCHOOL,)
                )
            ),
        )
        rows, total, parsed = await _execute(uc,
            query="x",
            location=LocationFilter(parish="Cascais"),
            filters=PropertyFilters(limit=10, offset=0),
        )
        # Critical: 3-tuple — the route handler needs parsed.nearby_pois
        # for matched/unmatched POI response composition.
        assert parsed.typology == Typology.APARTMENT
        assert parsed.nearby_pois == (PoiCategory.SCHOOL,)

    async def test_pagination_applies_over_ranked_list(self, repo):
        ids = []
        for _ in range(5):
            ids.append(await _seed(repo))
        matches = [VectorMatch(id=ids[i], score=1.0 - i * 0.1, metadata={}) for i in range(5)]
        uc = _make_uc(
            repo=repo,
            vector_index=_StubVectorIndex(returns=matches),
        )
        page1, total1, _ = await _execute(uc,
            query="x",
            location=LocationFilter(parish="Cascais"),
            filters=PropertyFilters(limit=2, offset=0),
        )
        assert [str(r.id) for r in page1] == [ids[0], ids[1]]
        assert total1 == 5

        page2, total2, _ = await _execute(uc,
            query="x",
            location=LocationFilter(parish="Cascais"),
            filters=PropertyFilters(limit=2, offset=2),
        )
        assert [str(r.id) for r in page2] == [ids[2], ids[3]]
        assert total2 == 5

    async def test_empty_matches_returns_empty(self, repo):
        await _seed(repo)
        uc = _make_uc(repo=repo, vector_index=_StubVectorIndex(returns=[]))
        rows, total, _ = await _execute(uc,
            query="x",
            location=LocationFilter(parish="Cascais"),
            filters=PropertyFilters(limit=10, offset=0),
        )
        assert rows == []
        assert total == 0

    async def test_zero_sql_candidates_skips_pinecone(self, repo):
        """When the SQL pre-filter returns 0, the vector query is
        skipped — no point burning a Pinecone call when nothing
        matches the structural criteria."""
        await _seed(repo, parish="Lisboa")  # different parish
        vi = _StubVectorIndex(returns=[VectorMatch(id="x", score=1.0, metadata={})])
        uc = _make_uc(repo=repo, vector_index=vi)
        rows, total, _ = await _execute(uc,
            query="x",
            location=LocationFilter(parish="Cascais"),
            filters=PropertyFilters(limit=10, offset=0),
        )
        assert rows == []
        assert total == 0
        # Pinecone was NOT called.
        assert vi.last_filter is None

    async def test_stale_vector_dropped_by_hydrate_filter(self, repo):
        a = await _seed(repo)
        b = await _seed(repo)
        # Flip b to DRAFT — Pinecone metadata may still say ACTIVE
        # but list_by_ids drops it at SQL.
        repo._rows[UUID(b)].status = PropertyStatus.DRAFT  # type: ignore[attr-defined]
        matches = [
            VectorMatch(id=b, score=0.9, metadata={}),  # stale
            VectorMatch(id=a, score=0.7, metadata={}),
        ]
        uc = _make_uc(repo=repo, vector_index=_StubVectorIndex(returns=matches))
        rows, total, _ = await _execute(uc,
            query="x",
            location=LocationFilter(parish="Cascais"),
            filters=PropertyFilters(limit=10, offset=0),
        )
        assert [str(r.id) for r in rows] == [a]
        assert total == 1


# ──────────── Cardinality guard ────────────


class TestCardinalityGuard:
    async def test_broad_mode_when_sql_saturates(self, repo):
        """When SQL pre-filter returns len == limit, switch to broad
        mode: Pinecone over namespace + post-intersect."""
        # Seed 3 listings; cap candidates at 3 so saturation triggers.
        ids = [await _seed(repo) for _ in range(3)]
        # Pinecone broad-mode call returns 5 matches; intersection
        # narrows to candidates.
        matches = [VectorMatch(id=ids[0], score=0.9, metadata={})]
        vi = _StubVectorIndex(returns=matches)
        uc = _make_uc(repo=repo, vector_index=vi, max_candidates=3)
        rows, total, _ = await _execute(uc,
            query="x",
            location=LocationFilter(parish="Cascais"),
            filters=PropertyFilters(limit=10, offset=0),
        )
        # Filter sent to Pinecone is status-only (no listing_id.in).
        assert vi.last_filter == {"status": {"eq": "active"}}
        # top_k overshot by broad_mode_overshoot.
        assert vi.last_top_k == TOP_K * 4
        assert [str(r.id) for r in rows] == [ids[0]]


# ──────────── Fail-open ────────────


class TestFailOpen:
    async def test_extractor_failure_uses_raw_query_as_remainder(self, repo):
        await _seed(repo)
        embed = _StubEmbed()
        uc = _make_uc(
            repo=repo,
            extractor=_StubExtractor(raises=RuntimeError("LLM timeout")),
            embed=embed,
        )
        await _execute(uc,
            query="raw user query",
            location=LocationFilter(parish="Cascais"),
            filters=PropertyFilters(limit=10, offset=0),
        )
        # Extractor failed → ParsedQuery(free_text_remainder=query) →
        # renderer produces "DESCRIPTION: raw user query".
        assert any("raw user query" in t for t in embed.called_with)

    async def test_sql_prefilter_failure_falls_through_to_broad_mode(self, repo):
        """SQL error → candidates=[], saturated=True → broad-mode
        Pinecone call (no candidate intersection because we have
        nothing to intersect against)."""
        await _seed(repo)
        # Patch the repo to raise on list_ids_for_search.
        original = repo.list_ids_for_search

        async def boom(**_kw):
            raise RuntimeError("SQL boom")

        repo.list_ids_for_search = boom  # type: ignore[assignment]

        vi = _StubVectorIndex(returns=[])
        uc = _make_uc(repo=repo, vector_index=vi)
        rows, total, _ = await _execute(uc,
            query="x",
            location=LocationFilter(parish="Cascais"),
            filters=PropertyFilters(limit=10, offset=0),
        )
        # Broad mode kicked in (status-only filter).
        assert vi.last_filter == {"status": {"eq": "active"}}
        repo.list_ids_for_search = original

    async def test_embed_failure_triggers_relational_fallback(self, repo):
        a = await _seed(repo, parish="Cascais")
        await _seed(repo, parish="Lisboa")  # excluded by location
        uc = _make_uc(
            repo=repo,
            embed=_StubEmbed(raises=RuntimeError("embed boom")),
        )
        rows, total, _ = await _execute(uc,
            query="x",
            location=LocationFilter(parish="Cascais"),
            filters=PropertyFilters(limit=10, offset=0),
        )
        # Fallback returns the SQL candidates (location-correct, unranked).
        assert {str(r.id) for r in rows} == {a}
        assert total == 1

    async def test_vector_query_failure_triggers_relational_fallback(self, repo):
        a = await _seed(repo)
        uc = _make_uc(
            repo=repo,
            vector_index=_StubVectorIndex(raises=RuntimeError("pinecone down")),
        )
        rows, total, _ = await _execute(uc,
            query="x",
            location=LocationFilter(parish="Cascais"),
            filters=PropertyFilters(limit=10, offset=0),
        )
        assert {str(r.id) for r in rows} == {a}


# ──────────── _render_query_for_embed ────────────


class TestRenderQueryForEmbed:
    def test_full_parsedquery_renders_all_sections(self):
        pq = ParsedQuery(
            typology=Typology.HOUSE,
            min_bedrooms=3,
            min_bathrooms=2,
            min_area_m2=100,
            has_pool=True,
            has_garden=True,
            nearby_pois=(PoiCategory.SCHOOL, PoiCategory.GYM),
            free_text_remainder="varanda",
        )
        text = _render_query_for_embed(pq)
        assert "TYPOLOGY: house" in text
        assert "CHARACTERISTICS: T3" in text
        assert "≥100m²" in text
        assert "2 casas de banho" in text
        assert "FEATURES: piscina, jardim" in text
        assert "NEARBY: school, gym" in text
        assert "DESCRIPTION: varanda" in text

    def test_empty_parsedquery_yields_empty_string(self):
        """Pure function — the use case is responsible for the fallback
        (`DESCRIPTION: <raw_query>`)."""
        assert _render_query_for_embed(ParsedQuery()) == ""

    def test_only_free_text_remainder(self):
        pq = ParsedQuery(free_text_remainder="some text")
        assert _render_query_for_embed(pq) == "DESCRIPTION: some text"

    def test_area_range(self):
        pq = ParsedQuery(min_area_m2=100, max_area_m2=200)
        assert "100-200m²" in _render_query_for_embed(pq)


# ──────────── _has_unevaluable_criterion ────────────


class TestPartitionAndRank:
    async def test_null_bedrooms_with_min_bedrooms_set_goes_partial(self, repo):
        t3 = await _seed(repo, chars={"num_of_bedrooms": 3})
        null_row = await _seed(repo, chars=None)
        matches = [
            VectorMatch(id=null_row, score=0.95, metadata={}),  # high score, but NULL
            VectorMatch(id=t3, score=0.5, metadata={}),
        ]
        uc = _make_uc(
            repo=repo,
            extractor=_StubExtractor(returns=ParsedQuery(min_bedrooms=3)),
            vector_index=_StubVectorIndex(returns=matches),
        )
        rows, _, _ = await _execute(uc,
            query="T3",
            location=LocationFilter(parish="Cascais"),
            filters=PropertyFilters(limit=10, offset=0),
        )
        # Matched bucket (t3) first; partial bucket (null_row) last.
        # Even though null_row had higher cosine, the partition pushes
        # it below the matched bucket.
        assert [str(r.id) for r in rows] == [t3, null_row]


class TestHasUnevaluableCriterion:
    def test_no_criteria_set_returns_false(self):
        # Stub row with everything None — but no parsed criteria set.
        # Should be in the matched bucket.
        class _Row:
            num_of_bedrooms = None
            num_of_bathrooms = None
            area_in_m2 = None
            has_pool = None
            has_garden = None
            has_elevator = None
            parking_spaces = None
            min_price = None

        assert _has_unevaluable_criterion(_Row(), ParsedQuery()) is False

    def test_min_bedrooms_set_row_null_returns_true(self):
        class _Row:
            num_of_bedrooms = None
            num_of_bathrooms = 2
            area_in_m2 = 100
            has_pool = True
            has_garden = True
            has_elevator = True
            parking_spaces = 1
            min_price = Decimal("100000")

        assert (
            _has_unevaluable_criterion(_Row(), ParsedQuery(min_bedrooms=3)) is True
        )

    def test_min_bedrooms_set_row_populated_returns_false(self):
        class _Row:
            num_of_bedrooms = 3
            num_of_bathrooms = None
            area_in_m2 = None
            has_pool = None
            has_garden = None
            has_elevator = None
            parking_spaces = None
            min_price = None

        assert (
            _has_unevaluable_criterion(_Row(), ParsedQuery(min_bedrooms=3)) is False
        )


# ──────────── Parallel execution ────────────


class TestParallelExecution:
    async def test_sql_prefilter_and_embed_run_in_parallel(self, repo):
        """Deterministic pin: the embed stub awaits an asyncio.Event
        that the SQL stub sets BEFORE returning. If asyncio.gather
        runs them sequentially, the embed coroutine would deadlock
        waiting for an event that's never set (because SQL hasn't
        started yet). The use case is wrapped in asyncio.wait_for
        with a small timeout — a non-parallel impl fails loudly."""
        await _seed(repo)
        event = asyncio.Event()

        original_prefilter = repo.list_ids_for_search

        async def signal_then_filter(**kw):
            # Allow embed to proceed first by setting the event.
            event.set()
            return await original_prefilter(**kw)

        repo.list_ids_for_search = signal_then_filter  # type: ignore[assignment]

        embed_started = asyncio.Event()
        original_embed_returns = [0.1, 0.2, 0.3]

        class _GatedEmbed:
            async def embed(self, text):
                embed_started.set()
                # Wait for SQL to signal before returning.
                await event.wait()
                return list(original_embed_returns)

        uc = _make_uc(
            repo=repo,
            embed=_GatedEmbed(),
            vector_index=_StubVectorIndex(returns=[]),
        )
        # If gather is sequential, embed completes first (no event yet
        # → it blocks forever) → wait_for raises TimeoutError. If
        # parallel, both run concurrently; SQL sets the event, embed
        # unblocks, gather completes.
        await asyncio.wait_for(
            _execute(
                uc,
                query="x",
                location=LocationFilter(parish="Cascais"),
                filters=PropertyFilters(limit=10, offset=0),
            ),
            timeout=1.0,
        )
        assert event.is_set()
        assert embed_started.is_set()
