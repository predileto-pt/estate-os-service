# Listing search v2 — structured query extraction + hybrid retrieval (ADR-014)

**Status:** draft (review pending)
**Owner:** Peter
**Created:** 2026-05-11
**ADR:** [014-structured-query-extraction-and-hybrid-retrieval](../../docs/adr/014-structured-query-extraction-and-hybrid-retrieval.md)

## Problem

ADR-013 phase 2 (shipped 2026-05-11) ships a free-text query rewriter → embed → cosine ANN pipeline. Quality bottleneck: deterministic facets named in the query (typology, T2/T3 bedroom counts, has_pool, has_garden, POI categories) are evaluated as **soft signals via cosine** even though the structural data exists on `property_listings` and could hard-filter at the vector layer.

Concretely: a query *"casa T3 com piscina perto de escola"* against today's pipeline:

1. Gets rewritten to *"casa T3 com piscina, perto de escola"* (LLM canonicalization).
2. Embeds the rewrite as one vector.
3. Cosine-ranks against listings whose canonical text mentions piscina, T3, casa, school somewhere.
4. Returns the top-k. A T2 with a strong "piscina" description and POIs near a school can outrank a T3 with a sparser description.

The structural data is already on the projection — `num_of_bedrooms`, `has_pool`, `has_garden`, `area_in_m2` — but it's not in the vector-index metadata, so the query side can't use it as a filter. v2 fixes this by:

- Returning a typed `ParsedQuery` from query understanding (not free text).
- Bumping vector-index metadata to `LISTING_INDEX_METADATA_V2` carrying the structural fields.
- Bumping canonical text to `LISTING_CANONICAL_TEXT_V3` so the embedded listing and the embedded query share a sectional structure aligned with the extraction schema.
- Hard-filtering at the vector layer on the deterministic facets the user explicitly mentioned.

## Goal

`GET /api/v1/listings/properties?q=…&parish=…` runs the v2 pipeline when `LISTINGS_SEARCH_ENABLED_V2=true`:

1. **Extract**: LLM parses the query into `ParsedQuery` (typology, min_bedrooms, has_pool, nearby_pois categories, etc.). Fail-open on extractor error → empty `ParsedQuery` with `free_text_remainder = query`.
2. **Embed**: render `ParsedQuery` as a sectional canonical-text-v3-shaped string, embed.
3. **ANN**: vector query with the AND of ADR-013 filters + new structural filters derived from `ParsedQuery`. Top-k.
4. **Hydrate**: same `list_by_ids` path as v1.
5. **Respond**: same `ListedPropertyResponse` shape — no change to the public API contract.

When the gate is off, the v1 read path runs unchanged.

## Non-goals

- **Cross-encoder re-ranking** — ADR-014 §9, deferred to v3.
- **Personalization** (saved searches, user history) — ADR-014 §9, deferred to v4.
- **Faceted result counts** ("X in Cascais, Y in Estoril, …") — deferred to v5.
- **Removing the v1 read path.** v1 stays callable behind its own gate for one release cycle so we can roll back if v2 underperforms.
- **A new canonical-text version for non-PT listings.** v3 is PT-tuned (Portuguese typology vocabulary, PT POI surface forms in the extractor prompt). EN/DE/FR follow in a separate spec when those markets light up.
- **Negation handling beyond a one-shot prompt instruction.** "Não preciso de piscina" doesn't set `has_pool=false`; it sets `has_pool=None`. Full polarity parsing is out of scope for v2.

## Approach

### Component changes

#### 1. `QueryExtractor` port — replaces `QueryUnderstandingService`

```python
# src/listings/application/ports/query_extractor.py
from typing import Protocol

class QueryExtractor(Protocol):
    async def extract(self, query: str) -> ParsedQuery: ...
```

`QueryUnderstandingService` from ADR-013 is **deprecated, not deleted**, until v1 is retired. Both ports coexist in the codebase during the parallel rollout window. The container wires one or the other depending on `LISTINGS_SEARCH_ENABLED_V2`.

#### 2. `ParsedQuery` value object

```python
# src/listings/domain/parsed_query.py
from dataclasses import dataclass
from decimal import Decimal

from listings.domain.models import Typology
from listings.domain.poi_category import POICategory  # closed enum, mirrors properties context

@dataclass(frozen=True)
class ParsedQuery:
    free_text_remainder: str
    typology: Typology | None = None
    min_bedrooms: int | None = None
    min_bathrooms: int | None = None
    min_area_m2: int | None = None
    max_area_m2: int | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    has_pool: bool | None = None
    has_garden: bool | None = None
    has_elevator: bool | None = None
    has_parking: bool | None = None
    nearby_pois: tuple[POICategory, ...] = ()
```

Frozen dataclass, matches existing project convention. No invariant — every field is optional; `ParsedQuery(free_text_remainder=query)` is the fail-open default.

#### 3. `POICategory` closed enum

Living in `listings.domain.poi_category` (re-exported from `properties` if/when properties owns it; otherwise inlined for now and refactored in a follow-up). Initial members:

```python
class POICategory(StrEnum):
    SCHOOL = "school"
    GYM = "gym"
    SUPERMARKET = "supermarket"
    RESTAURANT = "restaurant"
    HOSPITAL = "hospital"
    PHARMACY = "pharmacy"
    TRANSPORT = "transport"      # bus stop, metro station, train station
    BEACH = "beach"
    PARK = "park"
    SHOPPING_CENTER = "shopping_center"
```

The categories MUST match what `properties`' POI auto-discovery workflow tags listings with — otherwise the closed-vocabulary alignment collapses. **Open question** below on whether to import the enum from `properties` (cross-context import) or to define it in `listings` and assert equivalence via a contract test.

#### 4. LLM adapter — `LangChainQueryExtractor`

`src/listings/adapters/ai/langchain_query_extractor.py`. Uses LangChain `with_structured_output(ParsedQuery)` against `gpt-4o-mini` (reuses `OPENAI_API_KEY`). System prompt:

- Lists the closed POI vocabulary.
- Lists the closed typology vocabulary.
- "Extract only what the user explicitly mentioned. Missing fields stay null. No genre-defaults. No hallucination."
- "Map surface forms: 'academia'→`gym`, 'primária'/'colégio'→`school`, 'talho'/'mercearia' → `supermarket` (best fit; otherwise omit). When unsure, omit."
- "Treat negation conservatively: 'não preciso de piscina' → `has_pool=null`, NOT `has_pool=false`. Polarity parsing is out of scope for v2."
- "free_text_remainder is everything left after extraction — colloquial descriptors, qualifiers like 'jeitoso', 'bom estado'. Strip filler ('uma', 'que tenha')."
- Worked examples (~10).

Timeout: `SEARCH_LLM_TIMEOUT_SECONDS` (4s, same as v1).

#### 5. Identity adapter — `IdentityQueryExtractor`

`src/listings/adapters/inmemory/inmemory_query_extractor.py`. Returns `ParsedQuery(free_text_remainder=query)`. Used in tests and as the wired adapter when `LISTINGS_SEARCH_ENABLED_V2=false` (parallel to ADR-013's identity rewriter pattern).

#### 6. `SearchListingsV2` use case

`src/listings/application/use_cases/search_listings_v2.py`. Same five-stage shape as v1, with extraction + sectional re-rendering:

```python
class SearchListingsV2:
    def __init__(
        self,
        *,
        query_extractor: QueryExtractor,
        embedding_provider: EmbeddingProvider,
        vector_index: VectorIndex,
        property_listing_repo: PropertyListingRepository,
        namespace: str,
        top_k: int,
    ) -> None: ...

    async def execute(
        self,
        *,
        query: str,
        location: LocationFilter,
        filters: PropertyFilters,
    ) -> tuple[list[PropertyListing], int]:
        # 1. Extract. Fail-open: empty ParsedQuery on any error.
        try:
            parsed = await self._query_extractor.extract(query)
        except Exception:
            log.warning("search_v2.extract_failed", query=query)
            parsed = ParsedQuery(free_text_remainder=query)

        # 2. Re-render as sectional canonical-text-v3-shaped string.
        embed_text = _render_query_for_embed(parsed)

        # 3. Embed. Same fail-open as v1 → relational fallback.
        # 4. ANN with hybrid filter (location + structured route params + ParsedQuery hard filters).
        # 5. Hydrate via list_by_ids. Re-order by score. Paginate.
        ...
```

The `_render_query_for_embed` helper lives in the use case (or a sibling). Mirrors the canonical-text composer's v3 layout:

```
TYPOLOGY: <parsed.typology.value>           // only when set
CHARACTERISTICS: T<min_bedrooms>, <min_area_m2>m²   // only the parts the user mentioned
FEATURES: piscina, jardim, ...
NEARBY: school, gym, ...
DESCRIPTION: <parsed.free_text_remainder>
```

#### 7. `_build_filter_v2` hybrid filter builder

Lives on the use case. Returns a `VectorFilter` AND-clause shaped to match the new `LISTING_INDEX_METADATA_V2` schema. Critically: route-param filters take precedence over `ParsedQuery` filters for the same field (ADR-014 §2 conflict-resolution rule).

```python
@staticmethod
def _build_filter_v2(
    location: LocationFilter,
    filters: PropertyFilters,     # route-param filters (FE form)
    parsed: ParsedQuery,          # LLM-extracted filters
) -> VectorFilter:
    clauses: list[dict] = [{"status": {"eq": PropertyStatus.ACTIVE.value}}]

    # Location (unchanged from v1).
    if location.parish:
        clauses.append({"parish": {"eq": location.parish.lower().strip()}})
    # … municipality, district

    # Route-param filters (FE form) — take precedence over ParsedQuery.
    effective_typology = filters.typology or parsed.typology
    if effective_typology is not None:
        clauses.append({"typology": {"eq": effective_typology.value}})

    if filters.listing_type is not None:
        clauses.append({"listing_type": {"eq": filters.listing_type.value}})

    # Price: route param wins when set, otherwise ParsedQuery.
    eff_min_price = filters.min_price or parsed.min_price
    eff_max_price = filters.max_price or parsed.max_price
    if eff_min_price is not None:
        clauses.append({"price_eur": {"gte": float(eff_min_price)}})
    if eff_max_price is not None:
        clauses.append({"price_eur": {"lte": float(eff_max_price)}})

    # New v2 filters from ParsedQuery (no route-param sibling — only LLM-extracted).
    if parsed.min_bedrooms is not None:
        clauses.append({"num_of_bedrooms": {"gte": parsed.min_bedrooms}})
    if parsed.min_bathrooms is not None:
        clauses.append({"num_of_bathrooms": {"gte": parsed.min_bathrooms}})
    if parsed.min_area_m2 is not None:
        clauses.append({"area_in_m2": {"gte": parsed.min_area_m2}})
    if parsed.max_area_m2 is not None:
        clauses.append({"area_in_m2": {"lte": parsed.max_area_m2}})
    if parsed.has_pool is True:
        clauses.append({"has_pool": {"eq": True}})
    if parsed.has_garden is True:
        clauses.append({"has_garden": {"eq": True}})
    if parsed.has_elevator is True:
        clauses.append({"has_elevator": {"eq": True}})
    if parsed.has_parking is True:
        clauses.append({"has_parking": {"eq": True}})

    return {"and": clauses}
```

**Important nuance** (ADR-014 §"Risks" — hard filters over-narrowing): if a listing has `num_of_bedrooms IS NULL`, Pinecone's `gte` filter excludes it. We need to decide: do we include NULL rows (treat as "unknown, include") or exclude (treat as "doesn't satisfy")? See Open questions.

#### 8. Canonical text v3 composer

`src/listings/application/services/canonical_text.py` (existing file). Add a `render_v3()` that produces the sectional output. Drive by `CANONICAL_TEXT_VERSION` env var or config — wire the indexing path to pick the right version.

Schema:

```
TYPOLOGY: <typology>
CHARACTERISTICS: T<num_of_bedrooms>[, <area_in_m2>m²][, <num_of_bathrooms> casas de banho]
FEATURES: <comma-list of true booleans: piscina, jardim, elevador, garagem>
NEARBY: <comma-list of `<POICategory.value>@<distance_meters>m`, sorted by distance>
DESCRIPTION: <suffix-clipped agent text>
LOCATION: <parish>, <municipality>, <district>
PRICE: <min_price> EUR
```

Sections are absent when the underlying data is. Distance for NEARBY is rounded to the nearest 100m for stability (avoids unnecessary hash churn on minor POI distance updates).

#### 9. Vector-index metadata schema v2

`embedding_handler._index_metadata` adds the seven fields (ADR-014 §2 table). Schema constant `LISTING_INDEX_METADATA_V2`.

#### 10. Embedding-handler routing

The handler stays one handler with a version flag: `CANONICAL_TEXT_VERSION` and `METADATA_VERSION` settings drive which composer + which metadata builder run. During the parallel rollout, the worker can be configured to write to either namespace (v1: `…-v1`, v2: `…-v2`) — but in practice, ops will run a one-shot backfill into the v2 namespace, validate, and atomically flip both `VECTOR_INDEX_NAMESPACE` and `LISTINGS_SEARCH_ENABLED_V2`.

#### 11. Container wiring

Container takes a new optional `query_extractor: QueryExtractor | None = None`. When `query_extractor + embedding_provider + vector_index` are all wired, the container also constructs `search_listings_v2 = SearchListingsV2(...)`. The existing `search_listings` (v1) stays in place.

#### 12. Route handler

The `/properties` route checks `getattr(container, "search_listings_v2", None)` **before** `search_listings`:

```python
if normalized_q is None:
    # structured-filter path (unchanged)
elif getattr(container, "search_listings_v2", None):
    properties, total = await container.search_listings_v2.execute(...)
elif getattr(container, "search_listings", None):
    properties, total = await container.search_listings.execute(...)
else:
    # neither gate is on → fall through to structured-filter
```

Same defensive pattern as ADR-013's wiring. No domain change to the route response.

#### 13. Bootstrap + settings

New settings on `Settings`:

| Setting | Default | Description |
|---|---|---|
| `listings_search_enabled_v2` | `False` | Master gate for the v2 pipeline. |
| `canonical_text_version` | `"v2"` | Which canonical-text composer to render at index time. Flip to `"v3"` to enable v2 retrieval; flip back to `"v2"` to roll back (re-backfill required either direction). |
| `metadata_version` | `"v1"` | Same idea for the vector-index metadata schema. Pinned to `"v1"` until v2 backfill completes. |

Bootstrap: when `LISTINGS_SEARCH_ENABLED_V2=true`, construct `LangChainQueryExtractor`. When `false`, construct `IdentityQueryExtractor` so the container's `query_extractor` is always non-None and the route's branching stays simple.

#### 14. Backfill

Not in this spec's scope — separate spec lands a `listings-canonical-text-v3-backfill` (mirrors `2026-05-listings-canonical-text-backfill`). The backfill enqueues `PROPERTY_LISTING_UPDATED.v1` for every active listing, which the embedding handler picks up, re-renders canonical text v3, re-embeds, upserts into the v2 namespace.

### Test strategy

All unit test files flat under `tests/unit/listings/` (matches ADR-013's convention).

- **Unit** — `tests/unit/listings/test_parsed_query.py`: pin defaults, frozen-ness, that all-None construction is allowed (free_text_remainder may be empty).
- **Unit** — `tests/unit/listings/test_langchain_query_extractor.py`: stub `_llm.ainvoke` to return canned `ParsedQuery` payloads. Pin worked examples ("casa T3 com piscina perto de escola" → typology=HOUSE, min_bedrooms=3, has_pool=True, nearby_pois=(SCHOOL,)). Pin negation conservatism. Pin timeout + error paths.
- **Unit** — `tests/unit/listings/test_query_for_embed_renderer.py`: pin the sectional re-rendering of `ParsedQuery` matches the canonical-text-v3 shape. Empty `ParsedQuery` → just `DESCRIPTION: <query>`.
- **Unit** — `tests/unit/listings/test_canonical_text_v3.py`: pin the v3 composer output for representative listings.
- **Unit** — `tests/unit/listings/test_search_listings_v2_use_case.py`: every fail-open branch (extractor raises, embedder raises, vector raises) — observable behavior unchanged from v1. Plus the new v2-specific assertions: hybrid filter contains the right clauses, route-param/ParsedQuery conflict resolution works, NULL-handling for `gte` is documented and tested.
- **Unit** — `tests/unit/listings/test_index_metadata_v2.py`: pin the new metadata payload matches the schema for representative `PropertyListing` rows.
- **Integration** — `tests/integration/test_search_endpoint_v2.py`: parallel to the v1 integration test. Overrides the `listing_container` fixture with v2 wiring (`LangChainQueryExtractor` stubbed by `IdentityQueryExtractor` + stub embedder + in-memory vector index). Seeds listings + their canonical-text-v3 embeddings. Asserts hybrid retrieval behavior end-to-end.

### Rollout

1. Ship behind `LISTINGS_SEARCH_ENABLED_V2=false` + `CANONICAL_TEXT_VERSION=v2` + `METADATA_VERSION=v1` (no behavior change on prod).
2. Run the v3 backfill (separate spec) into the v2 namespace.
3. Validate offline against a manual PT query corpus.
4. Flip `LISTINGS_SEARCH_ENABLED_V2=true` + `VECTOR_INDEX_NAMESPACE=<v2>` in staging. Validate.
5. Flip in production.
6. After one release cycle, retire v1: remove `QueryUnderstandingService` and `SearchListings`, drop `LISTINGS_SEARCH_ENABLED`, delete the v1 namespace.

## Affected files / surfaces

### New
- `src/listings/application/ports/query_extractor.py` — `QueryExtractor` Protocol.
- `src/listings/domain/parsed_query.py` — `ParsedQuery` value object.
- `src/listings/domain/poi_category.py` — `POICategory` closed enum (or re-export from `properties`).
- `src/listings/adapters/ai/langchain_query_extractor.py` — LLM adapter (structured output).
- `src/listings/adapters/inmemory/inmemory_query_extractor.py` — identity adapter (returns `ParsedQuery(free_text_remainder=query)`).
- `src/listings/application/use_cases/search_listings_v2.py` — v2 orchestration class.
- `tests/unit/listings/test_parsed_query.py`
- `tests/unit/listings/test_langchain_query_extractor.py`
- `tests/unit/listings/test_query_for_embed_renderer.py`
- `tests/unit/listings/test_canonical_text_v3.py`
- `tests/unit/listings/test_search_listings_v2_use_case.py`
- `tests/unit/listings/test_index_metadata_v2.py`
- `tests/integration/test_search_endpoint_v2.py`

### Modified
- `src/listings/application/services/canonical_text.py` — add `render_v3`. v2 composer stays around until rollout completes.
- `src/listings/adapters/workers/embedding_handler.py` — `_index_metadata` schema v2 + composer-version dispatch.
- `src/listings/adapters/api/routes/listings.py` — route branching to prefer `search_listings_v2`.
- `src/listings/container.py` — wire `query_extractor` + `search_listings_v2`.
- `src/shared/entrypoints/bootstrap.py` — construct `LangChainQueryExtractor` under `LISTINGS_SEARCH_ENABLED_V2=true`, identity otherwise.
- `src/shared/config.py` — new settings: `listings_search_enabled_v2`, `canonical_text_version`, `metadata_version`.
- `.env.example` — append v2-side block.
- `README.md` § Listings Semantic Search Setup — add §9 "v2 — structured extraction + hybrid retrieval".
- `docs/features/listings.md` — extend "Search read path" with v2 specifics.

## Acceptance criteria

Each criterion phrases an **externally observable** behavior.

### Extraction
- [ ] "casa T3 com piscina perto de escola" → `ParsedQuery(typology=HOUSE, min_bedrooms=3, has_pool=True, nearby_pois=(SCHOOL,))`. Unit test on the LangChain adapter with the LLM stubbed.
- [ ] "T2 jeitoso com varanda em Cascais" → `ParsedQuery(typology=APARTMENT, min_bedrooms=2, free_text_remainder=contains "jeitoso" or "varanda")`. The `varanda` intent that doesn't fit the closed enum lands in `free_text_remainder`.
- [ ] "ginásio escola supermercado" → `ParsedQuery(nearby_pois=(GYM, SCHOOL, SUPERMARKET))`. Listing-style queries parse cleanly.
- [ ] "não preciso de piscina" → `ParsedQuery(has_pool=None)`. Negation is conservatively ignored.
- [ ] Extractor failure → `ParsedQuery(free_text_remainder=query)` and search still returns 200 with results.

### Hybrid retrieval
- [ ] Hard filters apply: a query mentioning "T3" excludes vectors with `num_of_bedrooms < 3` from the result set. Integration test seeds a T2 with a "perfectly matching" description and a T3 with a sparser description, asserts only the T3 returns.
- [ ] Soft signal applies: a query mentioning "perto de escola" (no other facets) ranks listings with `NEARBY: school@…` higher than those without — but doesn't exclude. Same in-memory vector index seeded.
- [ ] Conflict resolution: when route param `?typology=apartment` is set and the query mentions "casa", the route param wins. Integration test asserts the filter sent to the vector index has `typology=apartment`.
- [ ] `parsed.has_pool=True` adds `{"has_pool": {"eq": True}}` to the filter. `parsed.has_pool=None` adds nothing.

### Canonical text v3 + index metadata v2
- [ ] Composer renders a representative listing as the sectional layout described in §"Canonical text v3 composer".
- [ ] `_index_metadata` includes all seven new fields when the source row has them populated.
- [ ] `_index_metadata` omits fields the source row has NULL (consistent with the existing "None values are dropped" convention from `LISTING_INDEX_METADATA_V1`).

### Backwards compatibility
- [ ] `LISTINGS_SEARCH_ENABLED_V2=false` → v1 read path runs unchanged. All existing ADR-013 phase 2 integration tests still pass.
- [ ] `LISTINGS_SEARCH_ENABLED_V2=true` but no `search_listings_v2` wired (defensive) → route falls back to v1, then to structured-filter.
- [ ] Public `ListedPropertyResponse` shape unchanged.

### Hygiene
- [ ] `ruff check` clean, full unit + integration suite green.
- [ ] README + docs/features/listings.md updated with v2 specifics + the rollout playbook.

## Open questions

- **POICategory enum ownership.** Should `POICategory` live in `listings.domain.poi_category` (inlined, contract-tested against the values `properties` actually emits) or be imported from `properties.domain.poi_category` (cross-context import — a clear architectural smell unless the enum is treated as part of the carried-state event contract)? Cross-context imports of value-object enums are arguably OK because they're part of the event payload's published shape. Recommend inlining + contract test for the cleaner boundary; flag for review.
- **NULL handling on `gte`/`lte` filters.** When a listing has `num_of_bedrooms IS NULL`, Pinecone's `gte` filter excludes it. Two options: (a) treat NULL as "doesn't satisfy" and exclude (simpler, stricter retrieval). (b) Treat NULL as "unknown" and include via an OR clause (`{"or": [{"num_of_bedrooms": {"gte": 3}}, {"num_of_bedrooms": {"exists": False}}]}`). The Pinecone `exists` operator isn't in the port surface today. Recommend (a) for simplicity + add the option to the port surface in a follow-up if listings with NULL structural fields turn out to be common.
- **POI surface-form mapping confidence.** The LLM is asked to map "talho"/"mercearia" → `supermarket` (best fit). Some surface forms have no good fit (e.g. "cabeleireiro"). The prompt says "when unsure, omit." Is that the right default vs. landing them in `free_text_remainder`? Recommend "when unsure, omit from `nearby_pois` AND land in `free_text_remainder` so cosine can do something with it." Confirm.
- **Conflict resolution: ParsedQuery price overrides route-param price?** The spec currently says route-param wins (FE form is explicit). But the FE doesn't have a free-text price box; the only way for the user to express "até 500k" is in the query text. Recommend: when the route-param price is None and `parsed.min_price`/`max_price` is set, the parsed value wins (which the current sketch does correctly). Just call out explicitly.
- **`has_parking` source.** Listings carry `parking_spaces: int | None`, not a `has_parking: bool`. The vector metadata derives `has_parking = (parking_spaces is not None and parking_spaces > 0)`. Should we also surface `min_parking_spaces` as an extractable + filterable field for queries like "com 2 lugares de garagem"? Probably yes — easy addition. Confirm scope.

## Out of scope follow-ups

- **`listings-canonical-text-v3-backfill`** spec — covers re-indexing all active listings into the v2 namespace.
- **Cross-encoder re-ranker** (ADR-014 §9 v3). On top-50 → top-10 against the raw query.
- **Personalization** (saved searches, user history) (ADR-014 §9 v4).
- **Faceted result counts** (ADR-014 §9 v5).
- **Polarity parsing** — handle "não preciso de piscina" as `has_pool=False` (negative filter). Requires careful prompt design + a regression corpus.
- **`min_parking_spaces` filter** — exact-count parking requirements.
- **Multilingual extraction** — EN/DE/FR query support. The prompt is PT-tuned for v2.
- **EXISTS operator on the VectorIndex port** — supports the NULL-handling option (b) above.

## Commits

Conventional commits, scope = `listings`:

- `feat(listings): ParsedQuery value object + POICategory closed enum`
- `feat(listings): QueryExtractor port + identity adapter + LangChain adapter`
- `feat(listings): canonical-text v3 composer + _index_metadata v2 schema`
- `feat(listings): embedding handler version dispatch (v2/v3)`
- `feat(listings): SearchListingsV2 use case with hybrid retrieval`
- `feat(listings): route branching to prefer search_listings_v2`
- `chore(listings): wire v2 container + bootstrap + settings`
- `test(listings): integration test for /properties?q=... v2 hybrid path`
- `docs(listings): document v2 structured extraction + hybrid retrieval + rollout`
