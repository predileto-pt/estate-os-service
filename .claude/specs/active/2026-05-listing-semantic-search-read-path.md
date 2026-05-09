# Listing semantic search — read path (ADR-013 phase 2)

**Status:** draft
**Owner:** Peter
**Created:** 2026-05-09

## Problem

Phase 1 (`2026-05-listing-semantic-search.md`, shipped) embedded every published listing into Pinecone behind a `VectorIndex` port and got the indexing pipeline running steady-state. The vectors are there. But there's no public way to query them — `GET /api/v1/listings/properties` today is the structured-filter relational query from ADR-010, blind to embeddings. Users typing free text get nothing semantic back.

Phase 2 ships the read path: `GET /api/v1/listings/properties?q=<text>` runs the two-stage pipeline ADR-013 §5 sketched (query understanding → vector ANN → DB hydrate), returning vector-ranked, location-prefiltered, structured-filtered results.

## Goal

`GET /api/v1/listings/properties?q=<free-text>` answers PT free-text queries like *"apartamento bom em Lisboa perto de boas escolas"* with semantic-ranked listings, p95 < 800ms end-to-end. Empty `q` falls through to the existing structured-filter behavior unchanged.

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

### Pipeline (ADR-013 §5)

```
GET /api/v1/listings/properties?q=…&listing_type=…&typology=…&min_price=…&district=…
        │
        ▼
ListPropertiesV2 use case (route layer)
        │
        ├── q is empty / null  ──►  fall through to existing structured-filter
        │                            relational query (ADR-010 path). No change.
        │
        └── q is set
                │
                ▼
        SearchListings use case
                │
        ┌───────┴───────┐  asyncio.gather (parallel)
        ▼               ▼
LocationExtractor   QueryRewriter
   (LLM, 4s          (LLM, 4s
    timeout)          timeout)
   │                   │
   └────────┬──────────┘
            │  merge: extracted location → metadata filter
            │         rewritten query → embedder input
            ▼
   EmbeddingProvider.embed(rewritten_query)   (150ms p95)
            │
            ▼
   VectorIndex.query(
       vector,
       filter = AND(
           status = ACTIVE,
           extracted_location_filter,        # parish > municipality > district
           structured_filter,                 # listing_type, typology, price range
       ),
       top_k = VECTOR_INDEX_TOP_K,           # default 50
       namespace = VECTOR_INDEX_NAMESPACE,
   )                                          (100ms p95)
            │
            ▼
   DB hydrate:
   SELECT … FROM property_listings WHERE id = ANY(:ids) AND status='ACTIVE'
   Reorder rows by vector-index score map.    (50ms p95)
            │
            ▼
   JSON response (same shape as existing list endpoint, plus optional `_score` field)
```

Critical-path latency target: stage 0 parallel (max of ~300ms LLM ≈ 300ms) + 150ms embed + 100ms ANN + 50ms hydrate ≈ **600ms p95**, leaving ~200ms headroom on the 800ms budget.

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

### Filter translation: extracted location + structured params → `VectorFilter`

The metadata filter passed to `VectorIndex.query` is the AND of three blocks. Builder lives in `SearchListings`:

```python
def _build_filter(
    location: ExtractedLocation | None,
    params: SearchParams,
) -> VectorFilter:
    clauses: list[dict] = [{"status": {"eq": "ACTIVE"}}]

    # Location: most-specific level wins; fall back through hierarchy.
    if location is not None:
        if location.parish:
            clauses.append({"parish": {"eq": location.parish.lower().strip()}})
        elif location.municipality:
            clauses.append({"municipality": {"eq": location.municipality.lower().strip()}})
        elif location.district:
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

    return {"and": clauses} if len(clauses) > 1 else clauses[0]
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
- `src/listings/application/ports/location_extractor.py`
- `src/listings/application/ports/query_rewriter.py`
- `src/listings/domain/extracted_location.py` — `ExtractedLocation` value object.
- `src/listings/adapters/ai/langchain_location_extractor.py`
- `src/listings/adapters/ai/langchain_query_rewriter.py`
- `src/listings/adapters/inmemory/inmemory_location_extractor.py` (rule-based; doubles as production fallback adapter)
- `src/listings/adapters/inmemory/inmemory_query_rewriter.py`
- `src/listings/application/use_cases/search_listings.py`
- `src/listings/application/use_cases/_search_filter_builder.py` (or inline in the use case)
- `tests/unit/listings/application/use_cases/test_search_listings.py`
- `tests/unit/listings/adapters/inmemory/test_inmemory_location_extractor.py`
- `tests/integration/listings/test_search_endpoint.py`

### Modified
- `src/listings/adapters/api/routes/listings.py` — add `q` query param; route handler branches on its presence.
- `src/listings/container.py` — wire the two new ports + the use case.
- `src/shared/entrypoints/bootstrap.py` — construct LLM adapters under the gate.
- `src/shared/config.py` — `LISTINGS_SEARCH_ENABLED`, `SEARCH_LLM_MODEL`, `SEARCH_LLM_TIMEOUT_SECONDS`, `SEARCH_LLM_MAX_OUTPUT_TOKENS`, `SEARCH_QUERY_CACHE_TTL_SECONDS` (already declared in ADR §7).
- `src/listings/application/ports/listing_repository.py` — add `list_by_ids(ids: list[UUID]) -> list[ListedProperty]` (or extend existing).
- `src/listings/adapters/database/listing_repository.py` + `inmemory/inmemory_listing_repository.py` — implement.
- `.env.example` — append search-side block.
- `README.md` § Listings Semantic Search Setup — document the gate + LLM env vars.
- `docs/features/listings.md` — add "Search read path" section + endpoint behavior matrix.

## Acceptance criteria

- [ ] `GET /api/v1/listings/properties?q=apartamento+lisboa` returns vector-ranked results when `LISTINGS_SEARCH_ENABLED=true`, falls through to structured-filter when `false`.
- [ ] Empty `q` (or `q` not provided) falls through to the existing endpoint behavior unchanged — regression tests on the existing list endpoint pass.
- [ ] `LocationExtractor` extracts `Lisboa` from queries containing the city name; returns empty `ExtractedLocation` when no location is mentioned.
- [ ] `LocationExtractor` low-confidence path (multiple candidates) passes them as a metadata `IN` filter rather than `eq` — verified in unit test.
- [ ] `QueryRewriter` normalizes a colloquial PT query (typo'd or mixed-language) to a canonical form — golden test on a small fixture.
- [ ] `SearchListings.execute` runs stage 0 in parallel via `asyncio.gather` (verified by timing in a unit test).
- [ ] LLM stage timeout → fall open: vector ANN runs, results returned. Unit test stubs the LLM to time out, asserts results returned without exception.
- [ ] `EmbeddingProvider` failure → relational fallback. Unit test stubs the embedder to raise, asserts existing structured-filter results are returned.
- [ ] `VectorIndex.query` failure → relational fallback. Unit test asserts same.
- [ ] DB hydrate preserves vector-index score ordering (top match first). Integration test seeds the in-memory index, asserts response order.
- [ ] Top-k bound respected (response length ≤ `VECTOR_INDEX_TOP_K`).
- [ ] Latency budget — measured against the in-memory adapters, no LLM mocks: `SearchListings` end-to-end < 50ms p99 (sanity, no real network). Production budgets in ADR §8 are enforced via timeout configs, not test assertions.
- [ ] `ruff check` clean, full unit suite green.
- [ ] README + `docs/features/listings.md` updated.

## Open questions

- **LLM model choice.** ADR §7 placeholders `SEARCH_LLM_MODEL=gpt-...`. `gpt-4o-mini` is the cheap default; `gpt-5-mini` (when available) might be better for PT location extraction. Decision deferred to implementation; pin in `.env.example` with a comment about cost.
- **Score field on response.** Do we expose `_score` on each result for the frontend to render relevance? Default no — keeps the response shape symmetric with the existing endpoint. Easy to add later.
- **Pagination over vector results.** Current scope: top-k bounded. If queries routinely return >50 useful matches, we'd need cursor pagination over the score-ordered list. Out of scope; revisit.
- **`AddressParser` ↔ `LocationExtractor` overlap.** The address-enrichment handler already uses an LLM to parse listing addresses into parish/municipality/district. The query-time extractor does the same shape of work on user queries. Different prompts (address parsing vs query understanding), but the underlying capability is similar. Not collapsing them into one port for now — different SLAs (write-path enrichment can take 10s; read-path query extraction must be < 4s). Revisit if maintenance overhead grows.

## Out of scope follow-ups

- **Cross-encoder re-ranker** — ADR §6.7, §"Iteration plan v6". If retrieval quality of the cosine-ANN ranking falls short, we add a small re-scoring model on top-50 → top-10 against the raw query. New port, new LLM call site, new latency budget.
- **Search-side caching beyond in-memory.** Redis-backed query cache for popular searches if hit rate justifies it.
- **Cursor pagination over vector results.**
- **Faceted result counts.**
- **Search-quality observability** — log query → result IDs to a separate table for relevance evaluation. Privacy + retention design.
- **Multilingual query support** beyond PT — separate prompt tuning + extraction corpus for EN/DE/FR.
- **Synonym expansion** — properties tag a listing with extra search-time tokens (e.g., `T2`, `2 quartos`, `2BR` all map to the same listing). Currently relies on the multilingual embedder.

## Commits

Conventional commits, scope = `listings`:

- `feat(listings): LocationExtractor + QueryRewriter ports + in-memory adapters`
- `feat(listings): LangChain LLM adapters for location extraction + query rewriting`
- `feat(listings): SearchListings use case with two-stage pipeline + fail-open fallbacks`
- `feat(listings): GET /api/v1/listings/properties q param + route branching`
- `chore(listings): wire search-side container + bootstrap + settings`
- `docs(listings): document search read path + LLM env vars`
