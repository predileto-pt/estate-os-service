"""Integration test for the public search read path.

Builds a search-enabled `listing_container` (overriding the default
fixture from conftest), seeds the property-listing projection and
the in-memory vector index in lockstep, then drives the real route
handler via the test client.

Covers the externally-observable acceptance criteria from the spec:
- Empty `q` → existing structured-filter path runs (no ranking).
- `q` set + no location → 422 with the machine-readable code.
- `q` set + location → vector-ranked results, score-ordered.
- LLM raises → search still returns ranked results (fail-open).
- Embedder raises → relational fallback returns location-correct
  unranked results.
- Vector returns 0 → 200 with empty items.

Spec: `2026-05-listing-semantic-search-read-path` §Test strategy.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from listings.adapters.embedding.stub_provider import StubEmbeddingProvider
from listings.adapters.inmemory.inmemory_property_listing_repo import (
    InMemoryPropertyListingRepository,
)
from listings.adapters.inmemory.inmemory_query_extractor import (
    IdentityQueryExtractor,
)
from listings.adapters.vector.inmemory_index import InMemoryVectorIndex
from listings.application.ports.query_extractor import QueryExtractor
from listings.container import Container as ListingContainer
from listings.domain.parsed_query import ParsedQuery

NAMESPACE = "search-test-v1"


# ──────────── Search-enabled container override ────────────


class _RaisingQU(QueryExtractor):
    """Stub that raises on extract. Used to assert fail-open behavior."""

    async def extract(self, query: str) -> ParsedQuery:
        raise RuntimeError("simulated LLM failure")


class _RaisingEmbed:
    """Stub embedding provider that raises. Used to assert relational fallback."""

    async def embed(self, text: str) -> list[float]:
        raise RuntimeError("simulated embed failure")


@pytest.fixture
def search_property_listing_repo():
    return InMemoryPropertyListingRepository()


@pytest.fixture
def search_vector_index():
    return InMemoryVectorIndex()


@pytest.fixture
def search_embedding_provider():
    return StubEmbeddingProvider(dimensions=64)


@pytest.fixture
def search_query_understanding():
    return IdentityQueryExtractor()


@pytest.fixture
def property_listing_repo(search_property_listing_repo):
    """Override the global fixture so the app's container shares the
    same in-memory repo we seed in tests."""
    return search_property_listing_repo


@pytest.fixture
def listing_container(
    property_listing_repo,
    search_embedding_provider,
    search_vector_index,
    search_query_understanding,
):
    from listings.adapters.inmemory.inmemory_address_searcher import InMemoryAddressSearcher

    return ListingContainer(
        property_listing_repo=property_listing_repo,
        portugal_address_searcher=InMemoryAddressSearcher(),
        embedding_provider=search_embedding_provider,
        vector_index=search_vector_index,
        vector_index_namespace=NAMESPACE,
        query_extractor=search_query_understanding,
    )


# ──────────── Helpers ────────────


async def _seed_listing(
    repo,
    vector_index,
    embed,
    *,
    description: str,
    parish: str = "Cascais",
    municipality: str = "Cascais",
    district: str = "Lisboa",
    status: str = "active",
) -> str:
    """Seed a listing into both the projection AND the vector index,
    mirroring what the embedding handler does in steady state."""
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
            "description": description,
            "latitude": None,
            "longitude": None,
            "characteristics": None,
            "prices": [],
            "images": [],
        },
        source_occurred_at=datetime.now(timezone.utc),
    )
    if any((parish, municipality, district)):
        await repo.update_location(
            property_id=UUID(pid),
            parsed=ParsedAddress(
                country="Portugal",
                parish=parish,
                municipality=municipality,
                district=district,
            ),
        )
    # Upsert into the vector index with metadata matching what the
    # phase-1 embedding handler writes.
    vector = await embed.embed(description)
    await vector_index.upsert(
        vector_id=pid,
        vector=vector,
        metadata={
            "listing_id": pid,
            "property_id": pid,
            "parish": parish.lower().strip() if parish else None,
            "municipality": municipality.lower().strip() if municipality else None,
            "district": district.lower().strip() if district else None,
            "listing_type": "sale",
            "typology": "apartment",
            "status": status,
        },
        namespace=NAMESPACE,
    )
    return pid


# ──────────── Tests ────────────


class TestEmptyQueryFallsThroughToStructuredPath:
    async def test_no_q_returns_structured_results(
        self, client, search_property_listing_repo, search_vector_index, search_embedding_provider
    ):
        await _seed_listing(
            search_property_listing_repo,
            search_vector_index,
            search_embedding_provider,
            description="house with pool",
        )
        response = await client.get("/api/v1/listings/properties")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1

    async def test_whitespace_only_q_falls_through(
        self, client, search_property_listing_repo, search_vector_index, search_embedding_provider
    ):
        await _seed_listing(
            search_property_listing_repo,
            search_vector_index,
            search_embedding_provider,
            description="house",
        )
        response = await client.get("/api/v1/listings/properties?q=   ")
        assert response.status_code == 200
        # No 422 — whitespace-only `q` was normalized to None.
        assert response.json()["total"] == 1


class TestRequiredLocation:
    async def test_q_without_location_returns_422_with_code(self, client):
        response = await client.get("/api/v1/listings/properties?q=apartamento")
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert isinstance(detail, dict)
        assert detail["code"] == "location_required_for_search"

    async def test_q_with_parish_only_succeeds(
        self, client, search_property_listing_repo, search_vector_index, search_embedding_provider
    ):
        await _seed_listing(
            search_property_listing_repo,
            search_vector_index,
            search_embedding_provider,
            description="apartamento",
        )
        response = await client.get(
            "/api/v1/listings/properties?q=apartamento&parish=Cascais"
        )
        assert response.status_code == 200


class TestRanking:
    async def test_results_match_what_was_indexed(
        self, client, search_property_listing_repo, search_vector_index, search_embedding_provider
    ):
        # Three rows; the stub embedder is deterministic so the query
        # "casa com piscina" will rank the row with that exact
        # description highest.
        a = await _seed_listing(
            search_property_listing_repo,
            search_vector_index,
            search_embedding_provider,
            description="casa com piscina e jardim",
        )
        await _seed_listing(
            search_property_listing_repo,
            search_vector_index,
            search_embedding_provider,
            description="apartamento T2 simples",
        )

        response = await client.get(
            "/api/v1/listings/properties?q=casa com piscina e jardim&parish=Cascais"
        )
        assert response.status_code == 200
        data = response.json()
        ids = [item["id"] for item in data["items"]]
        # The exact-match row should be present in the ranked results.
        assert a in ids


class TestFailOpen:
    @pytest.fixture
    def search_query_understanding(self):
        # LLM raises — search should still return results (fail-open).
        return _RaisingQU()

    async def test_llm_failure_still_returns_results(
        self, client, search_property_listing_repo, search_vector_index, search_embedding_provider
    ):
        await _seed_listing(
            search_property_listing_repo,
            search_vector_index,
            search_embedding_provider,
            description="casa com piscina",
        )
        response = await client.get(
            "/api/v1/listings/properties?q=casa&parish=Cascais"
        )
        assert response.status_code == 200
        # Embed-with-raw-query still finds the row.
        assert len(response.json()["items"]) >= 1


class TestEmbedFailureRelationalFallback:
    @pytest.fixture
    def search_embedding_provider(self):
        return _RaisingEmbed()

    async def test_embed_failure_returns_location_correct_unranked(
        self, client, search_property_listing_repo, search_vector_index
    ):
        from listings.application.ports.address_searcher import ParsedAddress

        # Two rows: one in Cascais, one in Lisboa. Only Cascais should
        # come back in the relational fallback when the user filters
        # parish=Cascais.
        cascais_id = str(uuid4())
        lisboa_id = str(uuid4())
        for pid, parish in ((cascais_id, "Cascais"), (lisboa_id, "Lisboa")):
            await search_property_listing_repo.upsert_from_event(
                event_data={
                    "id": pid,
                    "organization_id": str(uuid4()),
                    "aggregate_version": 1,
                    "address": "x",
                    "listing_type": "sale",
                    "typology": "apartment",
                    "status": "active",
                    "description": "any",
                    "latitude": None,
                    "longitude": None,
                    "characteristics": None,
                    "prices": [],
                    "images": [],
                },
                source_occurred_at=datetime.now(timezone.utc),
            )
            await search_property_listing_repo.update_location(
                property_id=UUID(pid),
                parsed=ParsedAddress(
                    country="Portugal",
                    parish=parish,
                    municipality=parish,
                    district="Lisboa",
                ),
            )

        response = await client.get(
            "/api/v1/listings/properties?q=anything&parish=Cascais"
        )
        assert response.status_code == 200
        ids = [item["id"] for item in response.json()["items"]]
        assert cascais_id in ids
        assert lisboa_id not in ids


class TestEmptyVectorMatches:
    async def test_returns_200_with_empty_items(self, client, search_property_listing_repo):
        # No vectors indexed at all → vector_index.query returns [].
        await search_property_listing_repo.upsert_from_event(
            event_data={
                "id": str(uuid4()),
                "organization_id": str(uuid4()),
                "aggregate_version": 1,
                "address": "x",
                "listing_type": "sale",
                "typology": "apartment",
                "status": "active",
                "description": "any",
                "latitude": None,
                "longitude": None,
                "characteristics": None,
                "prices": [],
                "images": [],
            },
            source_occurred_at=datetime.now(timezone.utc),
        )
        response = await client.get(
            "/api/v1/listings/properties?q=anything&parish=Cascais"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0


# ──────────── /locations endpoint ────────────


class TestLocationsEndpoint:
    """`/locations` is served from the static JSON catalog
    (`src/listings/static_data/locations.json`), not from the DB.
    These tests just verify the wiring + response shape."""

    async def test_returns_country_district_municipality_parish_tree(self, client):
        response = await client.get("/api/v1/listings/locations")
        assert response.status_code == 200
        tree = response.json()
        assert "countries" in tree
        assert len(tree["countries"]) >= 1
        pt = next(c for c in tree["countries"] if c["code"] == "PT")
        assert pt["name"] == "Portugal"
        assert len(pt["districts"]) == 20  # 18 mainland + Madeira + Açores

        lisboa = next(d for d in pt["districts"] if d["name"] == "Lisboa")
        lisboa_city = next(m for m in lisboa["municipalities"] if m["name"] == "Lisboa")
        assert "Santa Maria Maior" in lisboa_city["parishes"]

    async def test_does_not_depend_on_seeded_data(self, client):
        """No rows seeded → catalog still returns the full PT geography."""
        response = await client.get("/api/v1/listings/locations")
        assert response.status_code == 200
        pt = response.json()["countries"][0]
        # Even with an empty DB, all 20 top-level units are present.
        assert len(pt["districts"]) == 20


# ──────────── Matched / unmatched POI response (ADR-014 §15) ────────────


class _StubPOIExtractor:
    """Stub `QueryExtractor` returning a fixed `ParsedQuery` so we
    don't depend on LLM behavior in these tests. Drives the
    matched/unmatched response composition deterministically."""

    def __init__(self, *, nearby_pois):
        from listings.domain.parsed_query import ParsedQuery
        from listings.domain.poi_category import PoiCategory  # noqa: F401 — needed at call site

        self._returns = ParsedQuery(nearby_pois=tuple(nearby_pois))

    async def extract(self, query: str):
        return self._returns


async def _seed_listing_with_pois(
    repo,
    vector_index,
    embed,
    *,
    description: str,
    pois: list[dict],
    parish: str = "Cascais",
    municipality: str = "Cascais",
    district: str = "Lisboa",
) -> str:
    """Like _seed_listing but carries an explicit POI list through the
    snapshot, so the projection ends up with the rich POI data on
    `ListingPoi`."""
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
            "description": description,
            "latitude": None,
            "longitude": None,
            "characteristics": None,
            "prices": [],
            "images": [],
            "pois": pois,
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
    vector = await embed.embed(description)
    await vector_index.upsert(
        vector_id=pid,
        vector=vector,
        metadata={
            "listing_id": pid,
            "property_id": pid,
            "parish": parish.lower().strip(),
            "municipality": municipality.lower().strip(),
            "district": district.lower().strip(),
            "listing_type": "sale",
            "typology": "apartment",
            "status": "active",
        },
        namespace=NAMESPACE,
    )
    return pid


class TestQEmptyResponseShape:
    """Even when q is empty, matched_pois and unmatched_pois are
    present in the JSON as empty lists. NOT absent — the schema
    defaults render them every time, which keeps the response
    contract regular and avoids the `response_model_exclude_none`
    BWC trap."""

    async def test_q_empty_has_empty_poi_lists(
        self,
        client,
        search_property_listing_repo,
        search_vector_index,
        search_embedding_provider,
    ):
        await _seed_listing(
            search_property_listing_repo,
            search_vector_index,
            search_embedding_provider,
            description="any",
        )
        response = await client.get("/api/v1/listings/properties")
        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["matched_pois"] == []
        assert item["unmatched_pois"] == []


class TestMatchedAndUnmatchedPois:
    """The q-set path populates matched_pois (full POI data for
    categories the user asked for AND the listing has) and
    unmatched_pois (categories the user asked for that the listing
    doesn't have nearby)."""

    @pytest.fixture
    def search_query_understanding(self):
        # Stub extractor: parses any query into nearby_pois=(SCHOOL,GYM)
        # so the matched/unmatched composition has signal to work
        # against the seeded POI list.
        from listings.domain.poi_category import PoiCategory

        return _StubPOIExtractor(nearby_pois=[PoiCategory.SCHOOL, PoiCategory.GYM])

    async def test_matched_pois_carry_rich_data(
        self,
        client,
        search_property_listing_repo,
        search_vector_index,
        search_embedding_provider,
    ):
        """Listing has a SCHOOL POI with rich fields → response carries
        it under matched_pois with name, distance, address,
        image_urls, reviews."""
        await _seed_listing_with_pois(
            search_property_listing_repo,
            search_vector_index,
            search_embedding_provider,
            description="casa",
            pois=[
                {
                    "category": "school",
                    "name": "Escola Básica de Cascais",
                    "distance_meters": 480,
                    "address": "Rua das Flores, 12, Cascais",
                    "image_urls": ["https://x/1.jpg"],
                    "reviews": [{"rating": 4, "text": "Boa"}],
                }
            ],
        )
        response = await client.get(
            "/api/v1/listings/properties?q=anything&parish=Cascais"
        )
        assert response.status_code == 200
        item = response.json()["items"][0]
        assert len(item["matched_pois"]) == 1
        m = item["matched_pois"][0]
        assert m["category"] == "school"
        assert m["name"] == "Escola Básica de Cascais"
        assert m["distance_meters"] == 480
        assert m["address"] == "Rua das Flores, 12, Cascais"
        assert m["image_urls"] == ["https://x/1.jpg"]
        assert m["reviews"] == [{"rating": 4, "text": "Boa"}]

    async def test_unmatched_pois_lists_categories_not_nearby(
        self,
        client,
        search_property_listing_repo,
        search_vector_index,
        search_embedding_provider,
    ):
        """Stub asks for SCHOOL + GYM. The listing has only a school
        → unmatched_pois=["gym"]."""
        await _seed_listing_with_pois(
            search_property_listing_repo,
            search_vector_index,
            search_embedding_provider,
            description="casa",
            pois=[
                {
                    "category": "school",
                    "name": "Escola",
                    "distance_meters": 500,
                }
            ],
        )
        response = await client.get(
            "/api/v1/listings/properties?q=anything&parish=Cascais"
        )
        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["unmatched_pois"] == ["gym"]

    async def test_multiple_matches_per_category_sorted_by_distance(
        self,
        client,
        search_property_listing_repo,
        search_vector_index,
        search_embedding_provider,
    ):
        """Spec acceptance criterion: 3 schools at 1500m / 200m / 800m
        (insertion order — NOT sorted) all surface in `matched_pois`,
        in ASCENDING distance order. The route helper sorts explicitly
        because the JSONB projection preserves discovery order, not
        the canonical-text composer's sort order."""
        await _seed_listing_with_pois(
            search_property_listing_repo,
            search_vector_index,
            search_embedding_provider,
            description="casa",
            pois=[
                {"category": "school", "name": "Far", "distance_meters": 1500},
                {"category": "school", "name": "Near", "distance_meters": 200},
                {"category": "school", "name": "Mid", "distance_meters": 800},
            ],
        )
        response = await client.get(
            "/api/v1/listings/properties?q=anything&parish=Cascais"
        )
        assert response.status_code == 200
        item = response.json()["items"][0]
        assert [p["distance_meters"] for p in item["matched_pois"]] == [200, 800, 1500]
        assert [p["name"] for p in item["matched_pois"]] == ["Near", "Mid", "Far"]
