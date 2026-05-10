# Listing semantic search — read path (ADR-013 phase 2)

**Status:** in-progress (review-cleared 2026-05-10; ready to implement)
**Owner:** Peter
**Created:** 2026-05-09

## Problem

Phase 1 (`2026-05-listing-semantic-search.md`, shipped) embedded every published listing into Pinecone behind a `VectorIndex` port and got the indexing pipeline running steady-state. The vectors are there. But there's no public way to query them — `GET /api/v1/listings/properties` today is the structured-filter relational query from ADR-010, blind to embeddings. Users typing free text get nothing semantic back.

Phase 2 ships the read path: `GET /api/v1/listings/properties?q=<text>` runs the two-stage pipeline ADR-013 §5 sketched (query understanding → vector ANN → DB hydrate), returning vector-ranked, location-prefiltered, structured-filtered results.

## Goal

`GET /api/v1/listings/properties?q=<free-text>&parish=…&municipality=…&district=…` answers PT free-text queries like *"casa com piscina perto de boas escolas"* (with `parish=Cascais` selected via FE dropdown) with semantic-ranked listings.

Two endpoint behaviors:

- **`q` empty / not provided** → fall through to the existing structured-filter path (ADR-010), unchanged. Location filter optional, behavior preserved.
- **`q` set** → the semantic search pipeline runs. **At least one of `parish` / `municipality` / `district` is required** (422 otherwise). The location filter is supplied structurally by the user (via FE selector populated by the new `/locations` endpoint), not extracted from the query text by an LLM.

A second new endpoint, `GET /api/v1/listings/locations`, returns the hierarchical tree of populated locations (district → municipality → parish) so the FE can render the selector.

### Latency budget (constraint, not a test)

ADR-013 §8 specifies the per-stage budgets:

| Stage | Budget |
|---|---|
| `QueryUnderstandingService` (LLM) | 300ms p95 (4s timeout) |
| `EmbeddingProvider.embed` | 150ms p95 |
| `VectorIndex.query` | 100ms p95 |
| DB hydrate | 50ms p95 |
| **Total p95 budget** | **600ms** (≈ 200ms headroom on the 800ms end-to-end target) |

These are enforced via timeout configs at the adapter layer, not via test assertions. The unit suite asserts ordering + correctness; production p95 is measured in metrics.

## Non-goals

- **Cross-encoder re-ranking** — ADR-013 v6, deferred until v1 retrieval quality demands it.
- **Personalized search** (user history, saved filters). Out for v1.
- **Faceted result counts** (matches per parish/typology). Separate spec.
- **Multilingual queries beyond PT** — the canonical text and the `QueryUnderstandingService` prompt are PT-tuned. EN/DE/FR queries work via the multilingual embedder but not optimized.
- **Search analytics / logging queries to a warehouse.** Privacy + storage decisions out of scope; query strings stay in app logs only at debug level.
- **Pagination beyond top_k** — first cut returns `top_k` (default 50) results. Cursor pagination over vector results is a follow-up.
- **Spell correction / fuzzy matching** beyond what the LLM rewriter does naturally.
- **Read-path caching** beyond the optional in-memory query cache from ADR §7 (SEARCH_QUERY_CACHE_TTL_SECONDS, default 300).

## Approach

### Read-model: single repo, projection-backed

The legacy `ListingRepository` (read mapping over the live `properties` table) was collapsed into `PropertyListingRepository` (the carried-state projection over `property_listings`) before this spec started — see commits `2794f119226c` (data layer expansion) + `332320c11888` (route migration + delete legacy). What that gives this spec for free:

- The route already reads from the projection. The structured `parish` / `municipality` / `district` columns the search filter wants are populated and indexed.
- `district` filter semantic is already exact-match against the column (was ILIKE on the address string in the legacy repo).
- `PropertyListing.images` and `.prices` are full lists projected from the snapshot — the hydrate step returns the full response shape via the same repo as the existing `q`-empty path.
- One repo, one domain type. No "which read-model" branching in the route handler.

### Pipeline (deviates from ADR-013 §5: drops `LocationExtractor`)

```
GET /api/v1/listings/properties
   ?q=…
   &parish=… | &municipality=… | &district=…   (≥ 1 required when q is set)
   &listing_type=…&typology=…&min_price=…
        │
        ▼
ListProperties use case (route layer)
        │
        ├── q empty / null  ──►  existing structured-filter path
        │                         (no location requirement, ADR-010 behavior preserved)
        │
        └── q set
                │
                ├── validate ≥ 1 of (parish, municipality, district) → 422 if none
                │
                ▼
        SearchListings use case   ← orchestration class, the “if-q-then-this” block
                │
                ▼
        QueryUnderstandingService  (LLM, 4s timeout)
                │
                ▼
        rewritten_query  ← intent-captured, retrieval-friendly form
                │
                ▼
        EmbeddingProvider.embed(rewritten_query)         (150ms p95)
                │
                ▼
        VectorIndex.query(
            vector,
            filter = AND(
                status = ACTIVE,
                user_location_filter,    ← parish | municipality | district
                                            from the param, not extracted
                structured_filter,        ← listing_type, typology, price range
            ),
            top_k = VECTOR_INDEX_TOP_K,
            namespace = VECTOR_INDEX_NAMESPACE,
        )                                                  (100ms p95)
                │
                ▼
        DB hydrate:
        SELECT … FROM property_listings WHERE id = ANY(:ids) AND status='ACTIVE'
        Reorder rows by vector-index score map.            (50ms p95)
                │
                ▼
        JSON response (same shape as existing list endpoint)
```

Critical-path latency target: 300ms LLM (rewriter only — `LocationExtractor` is gone) + 150ms embed + 100ms ANN + 50ms hydrate ≈ **600ms p95**, leaving ~200ms headroom on the 800ms budget. Better than the ADR sketch because the parallel stage 0a is no longer needed.

### Why no `LocationExtractor`

ADR-013 §5 sketched an LLM that extracts parish/municipality/district from the user's free-text query. With the FE selector + mandatory location param, **the user has already told us the location structurally**. The LLM extraction would only re-derive what we already have, with worse precision (occasional misclassification) and added latency. We trade a sometimes-wrong soft signal for a guaranteed-correct hard signal.

Captured in "Out of scope" as a possible v3 enhancement: a query-side LLM that *also* extracts secondary location signals from the free-text (e.g., "perto da Avenida da Liberdade") to use as re-ranking hints, not as filters. Strictly additive on top of the user-supplied filter.

### `SearchListings` — the if-q-then-this orchestration class

`src/listings/application/use_cases/search_listings.py`. Receives the validated request, returns ranked rows. Single entry point for everything that runs when `q` is set:

```python
class SearchListings:
    def __init__(
        self,
        query_understanding: QueryUnderstandingService,
        embedding_provider: EmbeddingProvider,
        vector_index: VectorIndex,
        listing_repo: ListingRepository,
        namespace: str,
        top_k: int,
    ) -> None:
        ...

    async def execute(
        self,
        *,
        query: str,                   # user's raw free-text — guaranteed non-empty here
        location: LocationFilter,     # validated: at least one level set
        params: SearchParams,         # listing_type, typology, price range, limit, offset
    ) -> tuple[list[PropertyListing], int]:
        # 1. Understand the query → retrieval-friendly form. Fail-open:
        #    the identity adapter returns `query` on timeout/raise, so
        #    this never raises out.
        rewritten = await self.query_understanding.rewrite(query)

        # 2. Embed. The vector path uses the user's (limit, offset) to
        #    size top_k — `top_k = min(VECTOR_INDEX_TOP_K_MAX, limit + offset)`.
        #    This keeps top_k bounded but lets pagination work for the
        #    first page natively.
        top_k = min(self.top_k_max, params.limit + params.offset)

        try:
            vector = await self.embedding_provider.embed(rewritten)
        except Exception:
            log.exception("search_listings.embed_failed", query=query)
            return await self._relational_fallback(location, params)

        # 3. ANN search.
        try:
            matches = await self.vector_index.query(
                vector=vector,
                filter=self._build_filter(location, params),
                top_k=top_k,
                namespace=self.namespace,
            )
        except Exception:
            log.exception("search_listings.vector_query_failed", query=query)
            return await self._relational_fallback(location, params)

        if not matches:
            return [], 0

        # 4. DB hydrate, preserving score order.
        rows = await self.property_listing_repo.list_by_ids(
            [UUID(m.id) for m in matches]
        )
        ordered = self._reorder_by_score(rows, matches)
        # 5. Apply pagination over the ranked list.
        page = ordered[params.offset : params.offset + params.limit]
        return page, len(ordered)

    async def _relational_fallback(
        self, location: LocationFilter, params: SearchParams,
    ) -> tuple[list[PropertyListing], int]:
        """When the vector path can't run (LLM/embed/vector failure),
        fall back to the same `PropertyListingRepository.list_active`
        the structured-filter (`q` empty) path uses, with the user's
        location filters applied as exact-match column predicates.

        Trade-off: we lose semantic ranking (the user's `q` text is
        ignored), but they keep getting results — same shape as if
        they'd searched without `q`. Better than 503'ing the page.
        """
        filters = PropertyFilters(
            listing_type=params.listing_type,
            typology=params.typology,
            min_price=params.min_price,
            max_price=params.max_price,
            parish=location.parish,
            municipality=location.municipality,
            district=location.district,
            limit=params.limit,
            offset=params.offset,
        )
        rows = await self.property_listing_repo.list_active(filters)
        total = await self.property_listing_repo.count_active(filters)
        return rows, total
```

Every external dependency is a port; the use case sees no adapters. Same pattern as `EnrichProperty`.

**Exception handling note**: `EmbeddingProvider` and `VectorIndex` adapter errors aren't wrapped in domain exceptions in v1 — the use case catches `Exception` broadly with a structured-log line. Spec for v2 would introduce typed wrappers (`EmbeddingError` / `VectorIndexError`) once we have observability data on which adapter failures actually need different handling. Keeping it simple now.

**Pagination**: the use case returns `(rows, total)` matching the existing list endpoint's tuple. `total` is the count of ranked candidates returned by Pinecone (capped by `top_k`), NOT the global match count. This is a known limitation of vector-ANN pagination: there's no cheap way to know how many listings would have matched at lower similarity. Document on the response.

### `QueryUnderstandingService` — the prompt for better retrieval

Renamed from the ADR's `QueryRewriter` to make the responsibility explicit. The job is: take the user's raw free-text query (often colloquial, possibly typo'd, mixed-language) and produce a **canonical retrieval form** that the embedder will encode well.

```python
class QueryUnderstandingService(Protocol):
    async def rewrite(self, query: str) -> str: ...
```

Worked example:

| Raw user query | Rewritten for retrieval |
|---|---|
| "Uma casa com varanda que tenha uma academia perto" | "casa com varanda, perto de ginásio" |
| "T2 jeitoso na zona de cascais com piscina" | "apartamento T2 em Cascais com piscina, em bom estado" |
| "casa pra família grande com jardim e perto de escola" | "casa familiar com jardim, perto de escolas" |
| "ginasio escola supermercado" | "perto de ginásio, escola, supermercado" |

What the LLM does:
- **Normalize colloquialisms** ("jeitoso" → "em bom estado"), strip filler ("uma", "que tenha").
- **Expand intent** ("família grande" → "familiar"), surface implicit features.
- **Synonym surfacing** ("academia" → "ginásio") so the canonical-text NEARBY line's PT terms hit.
- **Don't extract location** — the user already supplied it via the param.
- **Don't add features the user didn't mention** — no hallucination of "varanda" if not present.

Adapter: `LangChainQueryUnderstandingService` (LLM-backed) + `IdentityQueryUnderstandingService` (returns input unchanged, used for tests + as the LLM-failure fallback at the use-case level).

### Required-location validation

The route handler validates before reaching `SearchListings`:

```python
if q and not (parish or municipality or district):
    raise HTTPException(
        status_code=422,
        detail="When 'q' is provided, at least one of "
               "'parish', 'municipality', 'district' is required.",
    )
```

Returns a 422 with a machine-readable error code so the FE can render a nudge.

### `GET /api/v1/listings/locations` — hierarchical tree for the FE selector

New endpoint, public (same auth posture as the existing public listings endpoint). Returns the populated location tree derived from `property_listings`:

```http
GET /api/v1/listings/locations
```

```json
{
  "districts": [
    {
      "name": "Lisboa",
      "municipalities": [
        {
          "name": "Lisboa",
          "parishes": ["Santa Maria Maior", "Santo António", "Belém", ...]
        },
        {
          "name": "Cascais",
          "parishes": ["Cascais", "Estoril", ...]
        }
      ]
    },
    {
      "name": "Porto",
      "municipalities": [...]
    }
  ]
}
```

**Source of truth**: `SELECT DISTINCT parish, municipality, district FROM property_listings WHERE district IS NOT NULL OR municipality IS NOT NULL OR parish IS NOT NULL`. App-side groups the rows hierarchically. Districts/municipalities/parishes the user has zero published listings in are not returned — UX win, no empty regions in the dropdown.

**Caching**: in-memory cache with TTL `LISTINGS_LOCATIONS_CACHE_TTL_SECONDS` (default 300s — 5 min). Locations don't churn fast; the FE can cache the response too.

**Limits**: response is small (~few hundred entries for PT), gzipped fits well under 100KB.

### Fail-open semantics

| Failure | Behavior |
|---|---|
| `QueryUnderstandingService` times out / raises | Embed the raw user query verbatim. Search still runs, just less smart. |
| `EmbeddingProvider` raises | Fall back to relational filtering: existing structured-filter SQL filtered by the user-supplied location params. Logged + alerted. |
| `VectorIndex.query` raises | Same relational fallback as above. |
| Vector returns 0 matches | Return empty list (not an error). |
| `q` empty + no location filter | Existing structured-filter path runs, unchanged. |
| `q` set + no location filter | 422 with a clear error message (the FE shouldn't allow this state, but defense in depth). |

All failures log a structured event at WARN/ERROR level. Search keeps working; user gets results.

### Components to build

1. **`QueryUnderstandingService` port** at `src/listings/application/ports/query_understanding.py`.
2. **LLM adapter** at `src/listings/adapters/ai/langchain_query_understanding.py` — structured-output prompt, 4s timeout.
3. **Identity adapter** at `src/listings/adapters/inmemory/inmemory_query_understanding.py` — returns input unchanged. Used for tests + as the LLM-failure fallback at the use-case level.
4. **`LocationFilter` value object** at `src/listings/domain/location_filter.py` with at-least-one-level invariant.
5. **Extend `SearchParams`** — add `limit`, `offset` fields. Already partly exists in `PropertyFilters`; consider folding both into one or keeping them separate (decision at implementation).
6. **`SearchListings` use case** at `src/listings/application/use_cases/search_listings.py`. Orchestrates rewrite → embed → ANN → hydrate with fail-open at each step.
7. **`ListLocations` use case** at `src/listings/application/use_cases/list_locations.py` — hierarchical tree, TTL-cached.
8. **Two new methods on `PropertyListingRepository`**:
    - `list_locations() -> list[LocationTriple]` — distinct (parish, municipality, district) triples for the FE selector.
    - `list_by_ids(ids: list[UUID]) -> list[PropertyListing]` — for the hydrate step. Returns rows in arbitrary order; `SearchListings._reorder_by_score` re-sorts.
9. **Adapter implementations** for both new methods (SqlAlchemy + InMemory).
10. **Route changes** in `src/listings/adapters/api/routes/listings.py`:
    - Add `q`, `parish`, `municipality`, `district` query params to the existing `GET /api/v1/listings/properties`. Branch: `q` empty → existing structured-filter path (no change); `q` set → `SearchListings.execute(...)`.
    - 422 validation when `q` is set without a location.
    - New `GET /api/v1/listings/locations` route.
11. **Container wiring** in `src/listings/container.py` — add `query_understanding`, `search_listings`, `list_locations`. The existing `embedding_provider` and `vector_index` ports are reused (already wired in phase 1).
12. **Bootstrap** in `src/shared/entrypoints/bootstrap.py` — construct `LangChainQueryUnderstandingService` when `LISTINGS_SEARCH_ENABLED=true`. Identity adapter is used otherwise.
13. **Settings** in `src/shared/config.py`: `LISTINGS_SEARCH_ENABLED`, `SEARCH_LLM_MODEL`, `SEARCH_LLM_TIMEOUT_SECONDS`, `SEARCH_LLM_MAX_OUTPUT_TOKENS`, `LISTINGS_LOCATIONS_CACHE_TTL_SECONDS`, `VECTOR_INDEX_TOP_K_MAX`.

### Filter translation: user location + structured params → `VectorFilter`

The metadata filter passed to `VectorIndex.query` is the AND of three blocks. Builder lives in `SearchListings`:

```python
def _build_filter(
    location: LocationFilter,    # at-least-one-level invariant enforced at construction
    params: SearchParams,
) -> VectorFilter:
    clauses: list[dict] = [{"status": {"eq": "ACTIVE"}}]

    # Location: each level the user picked applies as an `eq`. Most
    # users pick exactly one (e.g. parish = Cascais), but if the FE
    # offers a "narrow further" pattern and sends multiple, all apply.
    if location.parish:
        clauses.append({"parish": {"eq": location.parish.lower().strip()}})
    if location.municipality:
        clauses.append({"municipality": {"eq": location.municipality.lower().strip()}})
    if location.district:
        clauses.append({"district": {"eq": location.district.lower().strip()}})

    # Structured params (existing query params from ADR-010).
    if params.listing_type:
        clauses.append({"listing_type": {"eq": params.listing_type.value}})
    if params.typology:
        clauses.append({"typology": {"eq": params.typology.value}})
    if params.min_price is not None:
        clauses.append({"price_eur": {"gte": float(params.min_price)}})
    if params.max_price is not None:
        clauses.append({"price_eur": {"lte": float(params.max_price)}})

    return {"and": clauses}
```

### Rollout

1. Code ships with `LISTINGS_SEARCH_ENABLED=false` (default). The route accepts `q` but ignores it — falls through to the structured-filter path. No external-API risk on prod.
2. Flip the flag in staging. Validate against a manual query corpus. Observe latency, fallback rates.
3. Flip in production once staging is clean.
4. (Out of scope, follow-up) Cross-encoder re-ranker if retrieval quality suffers (ADR-013 v6).

### Test strategy

- **Unit** — `tests/unit/listings/application/use_cases/test_search_listings.py` covers every fail-open branch with stubs for `QueryUnderstandingService`, `EmbeddingProvider`, `VectorIndex`, and an `InMemoryPropertyListingRepository` for hydrate.
- **Unit** — same file (or a sibling) covers `_build_filter` translation of `LocationFilter` + `SearchParams` → `VectorFilter`. Bare cases: parish-only, municipality-only, district-only, narrow-further (multiple levels), with-and-without structured params.
- **Unit** — `tests/unit/listings/domain/test_location_filter.py` pins the at-least-one-level invariant.
- **Unit** — golden tests for the `IdentityQueryUnderstandingService` (identity returns input unchanged) and the `LangChainQueryUnderstandingService` prompt against ~10 worked PT examples (deterministic when the LLM call is mocked with `langchain.fake.FakeListLLM` or similar).
- **Unit** — `tests/unit/listings/application/use_cases/test_list_locations.py` against the in-memory repo. Assert hierarchical tree shape, alphabetical ordering at each level, empty-DB returns `{"districts": []}`, TTL cache returns the same response twice without a second repo call.
- **Integration** — `tests/integration/listings/test_search_endpoint.py` against the in-memory adapters (seeded with ~20 listings), hits the real route handler:
    - Empty `q` → falls through to the existing structured-filter path.
    - `q` set without location → 422.
    - `q` set with location → ranked results, score-ordered, hydrate honors order.
    - LLM stub raises → search still returns results (fail-open).
    - Embedder stub raises → relational fallback returns location-correct (but unranked) results.
    - Vector returns 0 → empty list, 200.
- **Contract** — read path doesn't add new VectorIndex contract tests; phase 1's `test_inmemory_vector_index.py` already covers `query()`.
- **Contract** — read path doesn't add new VectorIndex contract tests; phase 1's `test_inmemory_vector_index.py` already covers `query()`.

## Affected files / surfaces

### New
- `src/listings/application/ports/query_understanding.py` — `QueryUnderstandingService` Protocol.
- `src/listings/adapters/ai/langchain_query_understanding.py` — LLM adapter with structured-output prompt.
- `src/listings/adapters/inmemory/inmemory_query_understanding.py` — identity rewriter (returns input unchanged); doubles as production LLM-failure fallback.
- `src/listings/domain/location_filter.py` — `LocationFilter` value object, enforces at-least-one-level invariant at construction.
- `src/listings/domain/search_params.py` — `SearchParams` value object (or extend the existing `PropertyFilters`; decision at implementation).
- `src/listings/application/use_cases/search_listings.py` — orchestration class.
- `src/listings/application/use_cases/list_locations.py` — hierarchical tree for the FE selector.
- `tests/unit/listings/application/use_cases/test_search_listings.py` — covers every fail-open branch.
- `tests/unit/listings/application/use_cases/test_list_locations.py`
- `tests/unit/listings/domain/test_location_filter.py` — invariant enforcement.
- `tests/integration/listings/test_search_endpoint.py` — end-to-end against in-memory adapters; asserts score order, location prefilter, fallbacks, 422 when q without location.

### Modified
- `src/listings/adapters/api/routes/listings.py` — add `q`, `parish`, `municipality`, `district` query params; 422 validation when `q` is set without location; new `GET /api/v1/listings/locations` route. Existing `_to_response` reused for both the structured-filter and search paths (same `PropertyListing` → `ListedPropertyResponse` mapping, since the read-model collapse already landed).
- `src/listings/adapters/api/schemas.py` — add a response schema for `GET /api/v1/listings/locations` (`LocationTreeResponse` or similar; small).
- `src/listings/application/ports/repositories/property_listing_repository.py` — add `list_by_ids` + `list_locations` methods.
- `src/listings/adapters/database/property_listing_repository.py` + `inmemory/inmemory_property_listing_repo.py` — implement the two new read methods.
- `src/listings/application/use_cases/list_properties.py` — no change; the existing structured-filter use case keeps reading from `PropertyListingRepository.list_active`. The route handler picks between `list_properties` and `search_listings` based on `q` presence.
- `src/listings/container.py` — wire `query_understanding`, `search_listings`, `list_locations`. `embedding_provider` and `vector_index` are already wired (phase 1).
- `src/shared/entrypoints/bootstrap.py` — construct `LangChainQueryUnderstandingService` under `LISTINGS_SEARCH_ENABLED=true`; otherwise wire the identity adapter.
- `src/shared/config.py` — `LISTINGS_SEARCH_ENABLED`, `SEARCH_LLM_MODEL`, `SEARCH_LLM_TIMEOUT_SECONDS`, `SEARCH_LLM_MAX_OUTPUT_TOKENS`, `LISTINGS_LOCATIONS_CACHE_TTL_SECONDS`, `VECTOR_INDEX_TOP_K_MAX`.
- `.env.example` — append search-side block.
- `README.md` § Listings Semantic Search Setup — document the gate + LLM env vars + the new endpoints + required-location semantics.
- `docs/features/listings.md` — add "Search read path" section + endpoint behavior matrix.

## Acceptance criteria

Each criterion phrases an **externally observable** behavior — passing it means the user-facing behavior is correct, not just that an internal function got called.

### Endpoint contract
- [ ] `GET /api/v1/listings/properties?q=apartamento&parish=Cascais` → 200 with vector-ranked results when `LISTINGS_SEARCH_ENABLED=true`; falls through to the structured-filter list (no ranking) when `false`.
- [ ] Empty `q` (or `q` not provided) → existing endpoint behavior unchanged. Regression tests on the existing list endpoint still pass. **Location is NOT required when `q` is empty** — browse without location works.
- [ ] `q` set with no location params → **422** with a machine-readable error code (`location_required_for_search` or similar). Unit + integration test.
- [ ] `q` set with any one location level → 200, search runs, results are filtered to that level.
- [ ] `q` set with multiple location levels → all apply as AND filters in the vector query.
- [ ] DB hydrate response preserves vector-index score ordering (top match first). Integration test asserts row order.
- [ ] `limit`/`offset` apply over the ranked list. `limit=2&offset=0` → 2 rows, top-2 by score. `limit=2&offset=2` → next 2 rows.
- [ ] Top-k bound respected: response length ≤ min(`VECTOR_INDEX_TOP_K_MAX`, `limit + offset`).
- [ ] `total` in the response equals the count of ranked candidates returned by Pinecone (capped by `top_k`), with a documentation note about the limitation.

### Fail-open behavior (assert externally observable)
- [ ] LLM rewrite times out / raises → search **still returns 200 with results**, ranked. Unit test stubs the LLM to raise; the response is non-empty.
- [ ] `EmbeddingProvider` raises → search **returns 200 with location-correct unranked results** (relational fallback). Unit test stubs the embedder; response items all match the user-supplied location filter.
- [ ] `VectorIndex.query` raises → same observable behavior as above.
- [ ] Vector returns 0 matches → 200 with empty `items`, `total=0`. (Not 404, not 500.)

### Domain invariants
- [ ] `LocationFilter(parish=None, municipality=None, district=None)` raises a domain error at construction.
- [ ] `QueryUnderstandingService` rewrites a colloquial PT query into a retrieval-friendly form. Golden test against ~10 worked examples (the ones in the spec).

### `/locations` endpoint
- [ ] `GET /api/v1/listings/locations` returns the hierarchical tree from populated rows. Districts/municipalities/parishes with zero published listings are excluded.
- [ ] Empty DB: returns `{"districts": []}` (200, not 500).
- [ ] Cached with TTL `LISTINGS_LOCATIONS_CACHE_TTL_SECONDS`. Second request inside the window doesn't re-hit the DB. Unit test with a fake clock.

### Hygiene
- [ ] `ruff check` clean, full unit suite green.
- [ ] README + `docs/features/listings.md` updated with the two endpoints + the required-location semantics.

## Open questions

- **LLM model choice.** ADR §7 placeholders `SEARCH_LLM_MODEL=gpt-...`. `gpt-4o-mini` is the cheap default; `gpt-5-mini` (when available) might be better for PT query understanding. Decision deferred to implementation; pin in `.env.example` with a comment about cost.
- **Score field on response.** Do we expose `_score` on each result for the frontend to render relevance? Default no — keeps the response shape symmetric with the existing endpoint. Easy to add later.
- **`/locations` shape — flat vs hierarchical.** The spec proposes hierarchical (district → municipality → parish). If the FE wants a flat searchable selector instead, we can return `[{district, municipality, parish}, ...]` triples. Both shapes derive from the same underlying SELECT DISTINCT; pick at implementation based on FE preference.

### Resolved (decisions captured for the record)

- **~~Required-location scope~~** → required only when `q` is set; empty `q` preserves the existing browse-without-location behavior.
- **~~Pagination over vector results~~** → `limit`/`offset` apply over the ranked list. `top_k = min(VECTOR_INDEX_TOP_K_MAX, limit + offset)`. Sufficient for the first page; cursor pagination over deep pages punted to a follow-up if usage warrants it.
- **~~Which repo / which read-model~~** → resolved before this spec started; single `PropertyListingRepository` over the `property_listings` projection.
- **~~`district` query-param semantic conflict~~** → resolved with the read-model collapse; the column is exact-match. The legacy ILIKE-on-address behavior is gone.
- **~~`_relational_fallback` definition~~** → calls `PropertyListingRepository.list_active(filters)` with the user's location + structured filters as exact-match column predicates. Unranked but location-correct.
- **~~`EmbeddingError`/`VectorIndexError` types~~** → punted; v1 catches `Exception` broadly with a structured-log line. Typed wrappers are a v2 concern once we have observability data on which adapter failures need different handling.

## Out of scope follow-ups

- **`LocationExtractor` for secondary location signals.** ADR §5 sketched an LLM that extracts location from the free-text query. The mandatory location param eliminates the need at v1, but a query like "casa perto da Avenida da Liberdade" carries a sub-municipality signal the user can't pick from the dropdown. A future v3 LLM stage could extract these as re-ranking *hints* (not hard filters), strictly additive on top of the user's filter.
- **Cross-encoder re-ranker** — ADR §6.7, §"Iteration plan v6". If retrieval quality of the cosine-ANN ranking falls short, we add a small re-scoring model on top-50 → top-10 against the raw query. New port, new LLM call site, new latency budget.
- **Search-side caching beyond in-memory.** Redis-backed query cache for popular searches if hit rate justifies it.
- **Cursor pagination over vector results.**
- **Faceted result counts** — "X listings in Cascais, Y in Estoril, …" alongside the search results. Useful UX but adds another aggregation pass.
- **Static PT location catalog** — instead of deriving locations from `property_listings` (only populated regions render), seed a complete PT geography catalog. Lets the FE always render the full tree even before any listings are indexed in a region. Trade-off: empty regions in the dropdown.
- **Search-quality observability** — log query → result IDs to a separate table for relevance evaluation. Privacy + retention design.
- **Multilingual query support** beyond PT — separate prompt tuning for EN/DE/FR queries.
- **Synonym tagging at index time** — properties tag a listing with extra search-time tokens (e.g., `T2`, `2 quartos`, `2BR` all map to the same listing). Currently relies on the multilingual embedder + the `QueryUnderstandingService`.

## Commits

Conventional commits, scope = `listings`:

- `feat(listings): LocationFilter + SearchParams value objects with at-least-one-location invariant`
- `feat(listings): QueryUnderstandingService port + identity adapter + LLM adapter`
- `feat(listings): list_by_ids + list_locations on PropertyListingRepository + adapters`
- `feat(listings): SearchListings use case with fail-open fallbacks`
- `feat(listings): ListLocations use case with TTL cache`
- `feat(listings): GET /api/v1/listings/properties q+location params + 422 validation`
- `feat(listings): GET /api/v1/listings/locations endpoint`
- `chore(listings): wire search container + bootstrap + settings`
- `docs(listings): document search read path + /locations endpoint + required-location semantics`
