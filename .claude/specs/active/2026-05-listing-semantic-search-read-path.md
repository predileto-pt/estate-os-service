# Listing semantic search — read path (ADR-013 phase 2)

**Status:** draft
**Owner:** Peter
**Created:** 2026-05-09

## Problem

Phase 1 (`2026-05-listing-semantic-search.md`, shipped) embedded every published listing into Pinecone behind a `VectorIndex` port and got the indexing pipeline running steady-state. The vectors are there. But there's no public way to query them — `GET /api/v1/listings/properties` today is the structured-filter relational query from ADR-010, blind to embeddings. Users typing free text get nothing semantic back.

Phase 2 ships the read path: `GET /api/v1/listings/properties?q=<text>` runs the two-stage pipeline ADR-013 §5 sketched (query understanding → vector ANN → DB hydrate), returning vector-ranked, location-prefiltered, structured-filtered results.

## Goal

`GET /api/v1/listings/properties?q=<free-text>&parish=…&municipality=…&district=…` answers PT free-text queries like *"casa com piscina perto de boas escolas"* (with `parish=Cascais` selected via FE dropdown) with semantic-ranked listings, p95 < 800ms end-to-end.

Two endpoint behaviors:

- **`q` empty / not provided** → fall through to the existing structured-filter path (ADR-010), unchanged. Location filter optional, behavior preserved.
- **`q` set** → the semantic search pipeline runs. **At least one of `parish` / `municipality` / `district` is required** (422 otherwise). The location filter is supplied structurally by the user (via FE selector populated by the new `/locations` endpoint), not extracted from the query text by an LLM.

A second new endpoint, `GET /api/v1/listings/locations`, returns the hierarchical tree of populated locations (district → municipality → parish) so the FE can render the selector.

## Non-goals

- **Cross-encoder re-ranking** — ADR-013 v6, deferred until v1 retrieval quality demands it.
- **Personalized search** (user history, saved filters). Out for v1.
- **Faceted result counts** (matches per parish/typology). Separate spec.
- **Multilingual queries beyond PT** — the canonical text and `LocationExtractor` prompts are PT-tuned. EN/DE/FR queries work via the multilingual embedder but not optimized.
- **Search analytics / logging queries to a warehouse.** Privacy + storage decisions out of scope; query strings stay in app logs only at debug level.
- **Pagination beyond top_k** — first cut returns `top_k` (default 50) results. Cursor pagination over vector results is a follow-up.
- **Spell correction / fuzzy matching** beyond what the LLM rewriter does naturally.
- **Read-path caching** beyond the optional in-memory query cache from ADR §7 (SEARCH_QUERY_CACHE_TTL_SECONDS, default 300).

## Approach

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
        params: SearchParams,         # listing_type, typology, min_price, max_price
    ) -> list[ListedProperty]:
        # 1. Understand the query → retrieval-friendly form.
        rewritten = await self.query_understanding.rewrite(query)  # fail-open: returns
                                                                    # `query` on timeout/raise

        # 2. Embed.
        try:
            vector = await self.embedding_provider.embed(rewritten)
        except EmbeddingError:
            return await self._relational_fallback(location, params)

        # 3. ANN search.
        try:
            matches = await self.vector_index.query(
                vector=vector,
                filter=self._build_filter(location, params),
                top_k=self.top_k,
                namespace=self.namespace,
            )
        except VectorIndexError:
            return await self._relational_fallback(location, params)

        if not matches:
            return []

        # 4. DB hydrate, preserving score order.
        rows = await self.listing_repo.list_by_ids([UUID(m.id) for m in matches])
        return self._reorder_by_score(rows, matches)
```

Every external dependency is a port; the use case sees no adapters. Same pattern as `EnrichProperty`.

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
4. **`SearchListings` use case** at `src/listings/application/use_cases/search_listings.py`. Orchestrates rewrite → embed → ANN → hydrate with fail-open at each step.
5. **`LocationFilter` value object** at `src/listings/domain/location_filter.py` with at-least-one-level invariant.
6. **`ListLocations` use case** at `src/listings/application/use_cases/list_locations.py` — hierarchical tree.
7. **`ListingRepository.list_locations()` port method** at `src/listings/application/ports/listing_repository.py` returning the distinct triples.
8. **`ListingRepository.list_by_ids(ids)` port method** for the hydrate step.
9. **Repo implementations** in both SQLAlchemy + InMemory adapters.
10. **Route changes** in `src/listings/adapters/api/routes/listings.py`:
    - Add `q`, `parish`, `municipality`, `district` query params to the existing `GET /api/v1/listings/properties`.
    - 422 validation when q is set without a location.
    - New `GET /api/v1/listings/locations` route.
11. **Container wiring** + **bootstrap** + **settings** (`LISTINGS_SEARCH_ENABLED`, `SEARCH_LLM_MODEL`, `SEARCH_LLM_TIMEOUT_SECONDS`, `SEARCH_LLM_MAX_OUTPUT_TOKENS`, `LISTINGS_LOCATIONS_CACHE_TTL_SECONDS`).

### Fail-open semantics

Every LLM and external call has fallback behavior — search degrades gracefully rather than 500's:

| Failure | Behavior |
|---|---|
| `LocationExtractor` times out / raises | Skip the location filter. Vector ANN runs with status + structured filters only; semantic rank carries the location burden. |
| `LocationExtractor` returns low-confidence (multiple candidates) | Use the most-specific level returned (parish > municipality > district) and pass remaining candidates as a metadata `IN` filter, not a single-value match. |
| `QueryRewriter` times out / raises | Embed the raw user query verbatim. |
| `EmbeddingProvider` raises | Fall back to relational filtering: existing structured-filter SQL with `district ILIKE %extracted%` if location was extracted. Logged + alerted. |
| `VectorIndex.query` raises | Same relational fallback as above. |
| `q` is empty string or missing | Skip stages 0–2 entirely. Fall through to the existing relational endpoint. Semantic search is a feature, not a requirement. |

All failures log a structured event at WARN/ERROR level for ops dashboards. The user gets results either way.

### Components to build

1. **`LocationExtractor` port** (already sketched in ADR §6) at `src/listings/application/ports/location_extractor.py`. Returns `ExtractedLocation(parish, municipality, district, confidence)`.
2. **`QueryRewriter` port** at `src/listings/application/ports/query_rewriter.py`. Returns rewritten query string.
3. **LLM adapters** (LangChain + OpenAI):
   - `src/listings/adapters/ai/langchain_location_extractor.py` — structured-output prompt that extracts parish/municipality/district + confidence from a PT query.
   - `src/listings/adapters/ai/langchain_query_rewriter.py` — rewrites colloquial / typo'd / mixed-language queries to canonical search vocabulary.
4. **Test doubles** at `src/listings/adapters/inmemory/`:
   - `inmemory_location_extractor.py` — rule-based regex matcher over a fixed PT location corpus (also serves as the LLM-failure fallback adapter in production).
   - `inmemory_query_rewriter.py` — identity rewriter (returns input unchanged) + a fixture-based one for tests.
5. **`SearchListings` use case** at `src/listings/application/use_cases/search_listings.py`. Orchestrates stage 0 (`asyncio.gather`), stage 1 (`VectorIndex.query`), stage 2 (DB hydrate via `ListingRepository.list_by_ids`). Sees only ports.
6. **Repo extension** — add `ListingRepository.list_by_ids(ids: list[UUID]) -> list[ListedProperty]` to the existing read-model port + adapters. Idempotent SELECT for the hydrate step.
7. **Route changes**:
   - `src/listings/adapters/api/routes/listings.py` — add `q: str | None = None` to the existing `GET /api/v1/listings/properties` endpoint. Branch: q empty → existing path; q present → `SearchListings.execute(q=q, filters=…)`.
8. **Container wiring** — `src/listings/container.py` adds `location_extractor`, `query_rewriter` ports.
9. **Bootstrap** — construct LLM adapters when `LISTINGS_SEARCH_ENABLED=true` (parallel to the indexing gate).
10. **Settings** — `SEARCH_LLM_MODEL`, `SEARCH_LLM_TIMEOUT_SECONDS`, `SEARCH_LLM_MAX_OUTPUT_TOKENS`, `LISTINGS_SEARCH_ENABLED`.

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

- **Unit** — `tests/unit/listings/application/use_cases/test_search_listings.py` exercises every fail-open branch using stub `LocationExtractor`/`QueryRewriter`/`EmbeddingProvider`/`VectorIndex`.
- **Unit** — `tests/unit/listings/services/test_search_filter_builder.py` (or fold into the use case test) for the location → filter translation, including hierarchy fallback + structured param merging.
- **Unit** — golden tests for the rule-based `InMemoryLocationExtractor` covering the top-N PT cities/parishes (Lisboa, Porto, Cascais, Sintra, Almada, …).
- **Integration** — `tests/integration/listings/test_search_endpoint.py` against the in-memory `VectorIndex` (seeded with 20 listings) hitting the real route handler. Assert score-ordered results, location prefilter behavior, fallback when LLM stub raises.
- **Contract** — read path doesn't add new VectorIndex contract tests; phase 1's `test_inmemory_vector_index.py` already covers `query()`.

## Affected files / surfaces

### New
- `src/listings/application/ports/query_understanding.py` — `QueryUnderstandingService` Protocol.
- `src/listings/adapters/ai/langchain_query_understanding.py` — LLM adapter with structured-output prompt.
- `src/listings/adapters/inmemory/inmemory_query_understanding.py` — identity rewriter (returns input unchanged); doubles as production LLM-failure fallback.
- `src/listings/domain/location_filter.py` — `LocationFilter` value object, enforces at-least-one-level invariant at construction.
- `src/listings/domain/search_params.py` — `SearchParams` value object wrapping listing_type/typology/price-range query params.
- `src/listings/application/use_cases/search_listings.py` — orchestration class.
- `src/listings/application/use_cases/list_locations.py` — hierarchical tree for the FE selector.
- `tests/unit/listings/application/use_cases/test_search_listings.py` — covers every fail-open branch.
- `tests/unit/listings/application/use_cases/test_list_locations.py`
- `tests/unit/listings/domain/test_location_filter.py` — invariant enforcement.
- `tests/integration/listings/test_search_endpoint.py` — end-to-end against in-memory adapters; asserts score order, location prefilter, fallbacks, 422 when q without location.

### Modified
- `src/listings/adapters/api/routes/listings.py` — add `q`, `parish`, `municipality`, `district` query params; 422 validation when q is set without location; new `GET /api/v1/listings/locations` route.
- `src/listings/application/ports/listing_repository.py` — add `list_by_ids(ids: list[UUID]) -> list[ListedProperty]` and `list_locations() -> list[LocationTriple]`.
- `src/listings/adapters/database/listing_repository.py` + `inmemory/inmemory_listing_repository.py` — implement.
- `src/listings/container.py` — wire `QueryUnderstandingService`, `SearchListings`, `ListLocations`.
- `src/shared/entrypoints/bootstrap.py` — construct LLM adapter under the gate.
- `src/shared/config.py` — `LISTINGS_SEARCH_ENABLED`, `SEARCH_LLM_MODEL`, `SEARCH_LLM_TIMEOUT_SECONDS`, `SEARCH_LLM_MAX_OUTPUT_TOKENS`, `LISTINGS_LOCATIONS_CACHE_TTL_SECONDS`.
- `.env.example` — append search-side block.
- `README.md` § Listings Semantic Search Setup — document the gate + LLM env vars + the new endpoints + required-location semantics.
- `docs/features/listings.md` — add "Search read path" section + endpoint behavior matrix.

## Acceptance criteria

- [ ] `GET /api/v1/listings/properties?q=apartamento&parish=Cascais` returns vector-ranked results when `LISTINGS_SEARCH_ENABLED=true`; falls through to structured-filter when `false`.
- [ ] Empty `q` (or `q` not provided) falls through to the existing endpoint behavior unchanged. Regression tests on the existing list endpoint still pass. **Location is NOT required when `q` is empty** — preserves existing browse behavior.
- [ ] `q` set with no location params (no parish, no municipality, no district) → **422** with a machine-readable error code. Unit + integration test.
- [ ] `q` set with any one location level → 200, search runs.
- [ ] `q` set with multiple location levels → all apply as AND filters in the Pinecone query (e.g. district=Lisboa AND municipality=Cascais both filter; vector search runs only on rows matching both).
- [ ] `QueryUnderstandingService` rewrites a colloquial PT query into a retrieval-friendly form. Golden test against ~10 worked examples (including the ones in the spec).
- [ ] LLM rewrite times out / raises → embed the raw query. Unit test stubs the LLM to time out, asserts the embedder receives the raw input.
- [ ] `EmbeddingProvider` failure → relational fallback (existing structured-filter SQL with the user-supplied location filter applied via SQL). Unit test asserts.
- [ ] `VectorIndex.query` failure → same relational fallback. Unit test asserts.
- [ ] DB hydrate preserves vector-index score ordering (top match first). Integration test.
- [ ] Top-k bound respected (response length ≤ `VECTOR_INDEX_TOP_K`).
- [ ] `LocationFilter` raises a domain error when constructed with all three levels None. Unit test.
- [ ] `GET /api/v1/listings/locations` returns the hierarchical tree from populated rows; districts/municipalities/parishes with zero published listings are excluded. Integration test seeds rows + asserts response shape.
- [ ] `/locations` response is cached with TTL `LISTINGS_LOCATIONS_CACHE_TTL_SECONDS`; second request inside the window doesn't re-hit the DB. Unit test with a fake clock.
- [ ] Latency: `SearchListings.execute` against in-memory adapters with stub LLM (no real network) < 50ms p99. Production budgets in ADR §8 are enforced via timeout configs, not test assertions.
- [ ] `ruff check` clean, full unit suite green.
- [ ] README + `docs/features/listings.md` updated with the two endpoints + the required-location semantics.

## Open questions

- **LLM model choice.** ADR §7 placeholders `SEARCH_LLM_MODEL=gpt-...`. `gpt-4o-mini` is the cheap default; `gpt-5-mini` (when available) might be better for PT query understanding. Decision deferred to implementation; pin in `.env.example` with a comment about cost.
- **Score field on response.** Do we expose `_score` on each result for the frontend to render relevance? Default no — keeps the response shape symmetric with the existing endpoint. Easy to add later.
- **Pagination over vector results.** Current scope: top-k bounded. If queries routinely return >50 useful matches, we'd need cursor pagination over the score-ordered list. Out of scope; revisit.
- **`/locations` shape — flat vs hierarchical.** The spec proposes hierarchical (district → municipality → parish). If the FE wants a flat searchable selector instead, we can return `[{district, municipality, parish}, ...]` triples. Both shapes derive from the same underlying SELECT DISTINCT; pick at implementation based on FE preference.
- **Required-location scope.** Currently: required only when `q` is set. If you want it required ALWAYS (browse-without-location is forbidden), that's a behavior change to the existing structured-filter endpoint and a one-line edit in the validator. Flagged for confirmation.

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
- `feat(listings): list_by_ids + list_locations on ListingRepository + adapters`
- `feat(listings): SearchListings use case with fail-open fallbacks`
- `feat(listings): ListLocations use case with TTL cache`
- `feat(listings): GET /api/v1/listings/properties q+location params + 422 validation`
- `feat(listings): GET /api/v1/listings/locations endpoint`
- `chore(listings): wire search container + bootstrap + settings`
- `docs(listings): document search read path + /locations endpoint + required-location semantics`
