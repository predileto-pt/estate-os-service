# Listing search — structured query extraction + hybrid retrieval (ADR-014)

**Status:** in-progress (review-3 cleared 2026-05-11; ready to implement)
**Owner:** Peter
**Created:** 2026-05-11
**ADR:** [014-structured-query-extraction-and-hybrid-retrieval](../../docs/adr/014-structured-query-extraction-and-hybrid-retrieval.md)

## Problem

ADR-013 phase 2 (shipped 2026-05-11, gated off) routes deterministic facets named in the query (typology, T2/T3 bedroom counts, has_pool, has_garden, POI categories) through cosine even though the structural data exists on `property_listings` and could be filtered at the database. The search isn't in production yet, so this spec **refactors the search in place** — replacing `QueryUnderstandingService` with `QueryExtractor`, bumping canonical-text v2→v3, introducing a SQL pre-filter on `property_listings` that runs in parallel with the embedding call, and enriching the response with matched/unmatched POI buckets per result. No parallel gate, no parallel namespace, no v1 callable side-by-side — we re-index dev/staging once and replace the wiring outright.

Concretely: a query *"casa T3 com piscina perto de escola"* today gets embedded as one vector and cosine-ranked against listings whose canonical text mentions piscina, T3, casa, school *somewhere*. A T2 with a strong "piscina" description can outrank a T3 with a sparser description. After this spec, the same query:

1. Extracts to `ParsedQuery(typology=HOUSE, min_bedrooms=3, has_pool=True, nearby_pois=(SCHOOL,))`.
2. In parallel: (a) SQL pre-filter on `property_listings` returns matching IDs (`WHERE typology='house' AND (num_of_bedrooms IS NULL OR num_of_bedrooms >= 3) AND (has_pool IS NULL OR has_pool = true) AND parish='Cascais' AND status='active' LIMIT 1000`); (b) the residue is embedded as a sectional canonical-text-v3-shaped string.
3. Pinecone ANN runs with `filter=AND(status="active", listing_id IN candidate_ids)` — cosine-ranks only the candidates. (Pinecone's `id` field isn't metadata-filterable, but the embedding handler already writes `listing_id` into the metadata payload — we filter on that instead.) Cardinality guard handles the rare "pre-filter too broad" case (see Approach).
4. Hydrate via `list_by_ids`. Partition matched/partial-data rows. Sort by score within each, concatenate.
5. Return matched POIs (the listing's `school` POI with full data — name, distance, address, image_urls, reviews) and unmatched POIs (categories the user asked for that this listing doesn't have nearby).

## Goal

`GET /api/v1/listings/properties?q=…&parish=…` runs the new pipeline when `LISTINGS_SEARCH_ENABLED=true` (same gate as before — no `_V2` suffix).

1. **Extract**: LLM parses the query into `ParsedQuery`. Fail-open on extractor error → `ParsedQuery(free_text_remainder=query)`.
2. **Parallel** (`asyncio.gather`):
   - **SQL pre-filter** on `property_listings`: AND of always-applied filters (`status='active'` + location), route-param hard filters (listing_type, typology, price), and `ParsedQuery` soft-hard filters (each as `(col IS NULL OR col <op> value)`). Returns up to `SEARCH_MAX_PRE_FILTER_CANDIDATES` (default 1000) matching IDs.
   - **Embed** the canonical-text-v3-shaped render of `ParsedQuery`.
3. **Cardinality guard + ANN**: when `|candidates| < SEARCH_MAX_PRE_FILTER_CANDIDATES` (i.e. the SQL `LIMIT` didn't saturate), Pinecone query with `filter={"and": [{"status": {"eq": "active"}}, {"listing_id": {"in": candidates}}]}`. When the LIMIT saturated (pre-filter was too broad), Pinecone query with `filter={"status": {"eq": "active"}}, top_k=top_k * SEARCH_BROAD_MODE_OVERSHOOT` then post-intersect with the candidate set.
4. **Hydrate**: `list_by_ids` (unchanged). Partition rows into matched / partial-data buckets. Sort by score within each. Concatenate.
5. **Respond**: `ListedPropertyResponse` gains `matched_pois: list[POIResponse]` and `unmatched_pois: list[str]` (categories) — only when `q` was set.

When `q` is empty/absent, the existing structured-filter path runs unchanged. Acceptance criterion: every ADR-013 phase 2 integration test still passes after this spec lands.

## Non-goals

- **Cross-encoder re-ranking** — ADR-014 §9, deferred. Hybrid retrieval should close most of the gap; re-rank only if quality data demands it.
- **Personalization** (saved searches, user history). Deferred.
- **Faceted result counts** ("X in Cascais, Y in Estoril, …"). Deferred.
- **Negation polarity beyond a one-shot prompt instruction.** "Não preciso de piscina" → `has_pool=None`, NOT `has_pool=False`. Full negation parsing is out of scope.
- **`min_parking_spaces` filter** — exact-count parking requirements like "com 2 lugares de garagem". TODO comment in the extractor + a follow-up bullet under "Out of scope follow-ups". Current scope only handles `has_parking: bool`.
- **A v2-gated parallel rollout.** Because the search hasn't been to production, we refactor in place — no `LISTINGS_SEARCH_ENABLED_V2`, no second namespace, no "v1 stays callable for one release cycle" complexity. If we ever ship search to prod and then need to bump schemas again, we'll exercise ADR-013's parallel-namespace pattern at that point.
- **A new canonical-text version for non-PT listings.** v3 is PT-tuned. EN/DE/FR follow when those markets light up.
- **Other `build_property_snapshot` field additions.** §13 extends the POI sub-payload with three fields (`address`, `image_urls`, `reviews`). If you need to surface other `PropertyPoi` fields downstream (e.g. `manually_edited`, `place_id`, `latitude`, `longitude`) or extend the snapshot in other ways, file a separate spec — don't piggyback on this one.
- **Type-aware price filtering.** `parsed.min_price` / `parsed.max_price` filter against the existing `PropertyListingModel.min_price` column (= the listing's LOWEST price across types — see ADR-013). For a rent-and-sale listing with rent=€1500/mo and sale=€500k, `min_price=1500`, so `parsed.min_price=250000` would exclude it even though the sale price meets the user's intent. Inherited limitation; type-aware price ranges (filter on `prices` JSONB by listing_type) are out of scope here.

## Approach

### Component changes (replace-in-place, not parallel)

#### 1. Replace `QueryUnderstandingService` with `QueryExtractor`

**Delete** in the same change:
- `src/listings/application/ports/query_understanding.py`
- `src/listings/adapters/ai/langchain_query_understanding.py`
- `src/listings/adapters/inmemory/inmemory_query_understanding.py`
- `tests/unit/listings/test_query_understanding.py`

**Add**:
- `src/listings/application/ports/query_extractor.py`:
  ```python
  from typing import Protocol

  class QueryExtractor(Protocol):
      async def extract(self, query: str) -> ParsedQuery: ...
  ```
- `src/listings/adapters/ai/langchain_query_extractor.py` — LangChain adapter; internal `_ExtractorResult` Pydantic model + map to `ParsedQuery` (see §4 for the full sketch — `with_structured_output` requires a Pydantic class, not a frozen dataclass).
- `src/listings/adapters/inmemory/inmemory_query_extractor.py` — identity adapter returning `ParsedQuery(free_text_remainder=query)`. Used in tests + as the wired adapter when `LISTINGS_SEARCH_ENABLED=false`.

The container's `query_understanding_service` attribute is **renamed** to `query_extractor` in the same commit.

#### 2. `ParsedQuery` value object

`src/listings/domain/parsed_query.py`:

```python
from dataclasses import dataclass, field
from decimal import Decimal

from listings.domain.models import Typology
from listings.domain.poi_category import PoiCategory  # closed enum, inlined for now (Open Q1)

@dataclass(frozen=True)
class ParsedQuery:
    free_text_remainder: str = ""
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
    # TODO: min_parking_spaces: int | None — landing here once we have
    # query-corpus data on whether users ask for exact parking counts
    # ("com 2 lugares de garagem"). Adding it later is additive on the
    # value object; the LLM prompt + filter builder follow.
    nearby_pois: tuple[PoiCategory, ...] = ()
```

Frozen dataclass; no invariant. `ParsedQuery()` is the fail-open default for empty queries that somehow get past the route validation.

#### 3. `PoiCategory` closed enum (inlined in listings)

`src/listings/domain/poi_category.py`:

```python
from enum import StrEnum

class PoiCategory(StrEnum):
    """Closed POI category vocabulary for the listings search read path.

    Inlined in listings rather than imported from properties — review
    settled on "inline for now" (2026-05-11). The members MUST stay in
    sync with `properties.domain.models.property_poi.PoiCategory`; a
    contract test asserts the value-set equivalence (see
    `tests/unit/listings/test_poi_category_contract.py`).
    """
    HOSPITAL = "hospital"
    BANK = "bank"
    GROCERY = "grocery"
    SCHOOL = "school"
    PHARMACY = "pharmacy"
    GYM = "gym"
    RESTAURANT = "restaurant"
    COFFEE_SHOP = "coffee_shop"
    LAUNDRY = "laundry"
    GAS_STATION = "gas_station"
    PUBLIC_TRANSIT = "public_transit"
    KINDERGARTEN = "kindergarten"
    PARK = "park"
    POST_OFFICE = "post_office"
    LIBRARY = "library"
    SHOPPING_MALL = "shopping_mall"
    BAKERY = "bakery"
    POLICE_STATION = "police_station"
    TIRE_SHOP = "tire_shop"
    AUTO_SHOP = "auto_shop"
```

Mirrors `properties.domain.models.property_poi.PoiCategory` value-for-value. The contract test compares the two enums' `set(member.value for member in enum)`. If properties bumps its enum, the contract test fails and we update listings in the same commit — the values are part of the carried-state event contract.

#### 4. LLM adapter — `LangChainQueryExtractor`

`src/listings/adapters/ai/langchain_query_extractor.py`. Structured output against `gpt-4o-mini`. Mirrors the existing `PortugalAddressSearcher` pattern (`src/listings/adapters/ai/portugal_address_searcher.py:68-89`) — `with_structured_output` requires a Pydantic BaseModel, NOT a frozen dataclass. Internal `_ExtractorResult` Pydantic model is what LangChain sees; the adapter maps it to the domain `ParsedQuery`:

```python
class _ExtractorResult(BaseModel):
    """Internal LLM-output envelope. Field-for-field mirror of
    ParsedQuery — see the comment on the domain dataclass for
    semantic meaning. List instead of tuple because Pydantic's
    JSON-schema generation prefers list types for structured
    output."""
    free_text_remainder: str = ""
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
    nearby_pois: list[PoiCategory] = []


class LangChainQueryExtractor:
    def __init__(self, *, model, openai_api_key, timeout_seconds, max_output_tokens):
        self._llm = ChatOpenAI(
            model=model, api_key=openai_api_key, temperature=0,
            max_tokens=max_output_tokens,
        ).with_structured_output(_ExtractorResult)
        self._timeout = timeout_seconds

    async def extract(self, query: str) -> ParsedQuery:
        try:
            result = await asyncio.wait_for(
                self._llm.ainvoke([SystemMessage(content=_SYSTEM_PROMPT),
                                   HumanMessage(content=query)]),
                timeout=self._timeout,
            )
        except Exception:
            log.exception("query_extractor.langchain.failed", query=query)
            raise
        r: _ExtractorResult = result  # type: ignore[assignment]
        return ParsedQuery(
            free_text_remainder=r.free_text_remainder,
            typology=r.typology,
            min_bedrooms=r.min_bedrooms,
            min_bathrooms=r.min_bathrooms,
            min_area_m2=r.min_area_m2,
            max_area_m2=r.max_area_m2,
            min_price=r.min_price,
            max_price=r.max_price,
            has_pool=r.has_pool,
            has_garden=r.has_garden,
            has_elevator=r.has_elevator,
            has_parking=r.has_parking,
            nearby_pois=tuple(r.nearby_pois),
        )
```

System prompt:

- Lists the closed `PoiCategory` vocabulary explicitly with surface-form hints ("primária"/"colégio"/"escola" → `school`; "academia"/"ginásio" → `gym`).
- Lists the closed `Typology` vocabulary.
- "Extract only what the user explicitly mentioned. Missing fields stay null. No genre-defaults. No hallucination."
- "Treat negation conservatively: 'não preciso de piscina' → has_pool=null, NOT has_pool=false."
- "When a POI surface form doesn't map cleanly onto the closed vocabulary (e.g. 'cabeleireiro'), OMIT it from `nearby_pois` AND include the surface form in `free_text_remainder` so cosine can do something with it." (Open Q3 resolved as "include in remainder.")
- "`free_text_remainder` carries everything left after extraction — colloquial descriptors, qualifiers like 'jeitoso'/'bom estado', off-vocabulary POIs. Strip filler ('uma', 'que tenha', 'pra')."
- Worked examples (~10), pulled from the acceptance criteria below.

Timeout: `SEARCH_LLM_TIMEOUT_SECONDS` (4s, same as before).

#### 5. Identity adapter — `IdentityQueryExtractor`

`src/listings/adapters/inmemory/inmemory_query_extractor.py`. Returns `ParsedQuery(free_text_remainder=query)`. Used in tests and when `LISTINGS_SEARCH_ENABLED=false`.

#### 6. `SearchListings` use case — replace the implementation

The existing `src/listings/application/use_cases/search_listings.py` is rewritten in place. Same constructor, same `execute` signature, same fail-open envelope — but the internals change:

```python
class SearchListings:
    def __init__(
        self,
        *,
        query_extractor: QueryExtractor,         # was: query_understanding
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
    ) -> tuple[list[PropertyListing], int, ParsedQuery]:
        # Returns ParsedQuery too — the route handler needs
        # `parsed.nearby_pois` to compose matched/unmatched POIs
        # on the response.
        ...
```

Internals:

1. **Extract.** Fail-open: `ParsedQuery(free_text_remainder=query)` on exception.
2. **Render** `ParsedQuery` as the canonical-text-v3-shaped embed string via `_render_query_for_embed`.
3. **Parallel stage** — `asyncio.gather(..., return_exceptions=True)`. **The `return_exceptions=True` is load-bearing**: default `gather` re-raises the first exception, which would defeat the per-stage fail-open envelope.

   ```python
   candidates_or_err, vector_or_err = await asyncio.gather(
       self._repo.list_ids_for_search(
           location=location,
           route_filters=filters,
           parsed=parsed,
           limit=self._max_pre_filter_candidates,
       ),
       self._embedding_provider.embed(embed_text),
       return_exceptions=True,
   )
   if isinstance(candidates_or_err, Exception):
       log.exception("search_listings.sql_prefilter_failed", query=query)
       candidates, saturated = [], True   # broad-mode falls through
   else:
       candidates = candidates_or_err
       saturated = len(candidates) >= self._max_pre_filter_candidates
   if isinstance(vector_or_err, Exception):
       log.exception("search_listings.embed_failed", query=query)
       return await self._relational_fallback(
           candidates=candidates, parsed=parsed, filters=filters,
       )
   vector = vector_or_err
   ```

4. **Cardinality guard + ANN.** Run the vector query under a try/except so vector-index exceptions also trigger `_relational_fallback`:

   ```python
   try:
       matches = await self._run_vector_query(
           vector=vector, candidates=candidates, cardinality_saturated=saturated,
       )
   except Exception:
       log.exception("search_listings.vector_query_failed", query=query)
       return await self._relational_fallback(
           candidates=candidates, parsed=parsed, filters=filters,
       )
   ```

   The fallback reuses the SQL candidates already computed in stage 3 — so a user with `?parish=Cascais&q="T3 com piscina"` whose vector path fails still gets back **only T3+pool Cascais listings**, not all Cascais listings (which would defeat the value of extraction). Sketch:

   ```python
   async def _relational_fallback(
       self,
       *,
       candidates: list[UUID],
       parsed: ParsedQuery,
       filters: PropertyFilters,
   ) -> tuple[list[PropertyListing], int, ParsedQuery]:
       """Vector path failed. Reuse the SQL pre-filter candidates and
       skip the ANN ranking. Apply partition-and-rank so NULL-data
       rows still go to the bottom of the page (deterministic order
       within each bucket: created_at desc, id desc — no cosine
       available). Pagination applies just like the happy path."""
       if not candidates:
           return [], 0, parsed
       # Cap to top_k before hydrate — same bound the happy path uses
       # so the response shape stays predictable.
       rows = await self._property_listing_repo.list_by_ids(
           candidates[: self._top_k]
       )
       matched, partial = _split_buckets(rows, parsed)
       matched.sort(key=lambda r: (r.created_at, str(r.id)), reverse=True)
       partial.sort(key=lambda r: (r.created_at, str(r.id)), reverse=True)
       ordered = matched + partial
       page = ordered[filters.offset : filters.offset + filters.limit]
       return page, len(ordered), parsed
   ```
5. **Hydrate** via `list_by_ids` (filters `status='active'` at SQL — defense in depth).
6. **`_partition_and_rank`** (replaces `_reorder_by_score`): rows where every set `ParsedQuery` criterion was evaluable against non-NULL columns → matched bucket. Rows where ≥1 criterion couldn't be evaluated (NULL on the column) → partial bucket. Each bucket ranked by cosine. Concatenate. `total = len(matched) + len(partial)` (mirrors ADR-013 v1's "post-hydrate count" semantic).
7. Paginate over the concatenation: `page = ordered[filters.offset : filters.offset + filters.limit]`.
8. Return `(page, total, parsed)`.

The route handler (§12) updates its call site to unpack the new 3-tuple.

#### 7. `_render_query_for_embed` helper

Mirrors the canonical-text-v3 layout (§9 below). Same module as `SearchListings` or a sibling:

```python
def _render_query_for_embed(parsed: ParsedQuery) -> str:
    sections = []
    if parsed.typology:
        sections.append(f"TYPOLOGY: {parsed.typology.value}")

    chars = []
    if parsed.min_bedrooms:
        chars.append(f"T{parsed.min_bedrooms}")
    if parsed.min_area_m2 or parsed.max_area_m2:
        # render as a range or floor/ceiling
        ...
    if parsed.min_bathrooms:
        chars.append(f"{parsed.min_bathrooms} casas de banho")
    if chars:
        sections.append(f"CHARACTERISTICS: {', '.join(chars)}")

    features = []
    if parsed.has_pool:    features.append("piscina")
    if parsed.has_garden:  features.append("jardim")
    if parsed.has_elevator: features.append("elevador")
    if parsed.has_parking: features.append("garagem")
    if features:
        sections.append(f"FEATURES: {', '.join(features)}")

    if parsed.nearby_pois:
        sections.append(f"NEARBY: {', '.join(p.value for p in parsed.nearby_pois)}")

    if parsed.free_text_remainder.strip():
        sections.append(f"DESCRIPTION: {parsed.free_text_remainder.strip()}")

    return "\n".join(sections)
```

Empty `ParsedQuery` yields an empty string. **The guard lives in the use case**, not in the helper (which stays a pure function of `ParsedQuery`):

```python
embed_text = _render_query_for_embed(parsed)
if not embed_text.strip():
    # Defensive: extractor produced an empty ParsedQuery (e.g. LLM
    # returned `{}`). Fall back to the raw query as a DESCRIPTION:
    # block so the embedder has SOMETHING to encode.
    embed_text = f"DESCRIPTION: {query}"
```

In practice this branch should be rare — even a one-word query lands in `free_text_remainder` via the prompt's "everything left after extraction" rule.

#### 8. SQL pre-filter — `list_ids_for_search` repo method + cardinality guard

A new repository read method narrows the candidate set on `property_listings` before the vector query. Lives on `PropertyListingRepository`:

```python
# src/listings/application/ports/repositories/property_listing_repository.py
@abstractmethod
async def list_ids_for_search(
    self,
    *,
    location: LocationFilter,
    route_filters: PropertyFilters,
    parsed: ParsedQuery,
    limit: int,
) -> list[UUID]:
    """Pre-filter candidate listing IDs for the search read path.

    Applies status='active' + location + route-param hard filters
    + ParsedQuery soft-hard filters (each as `col IS NULL OR
    col <op> value`) and returns up to `limit` matching IDs.

    **Saturation contract**: a result with `len == limit` is the
    caller's signal that the SQL filter was too broad to push down
    to the vector index. The caller's cardinality guard reads this
    as "fall back to a broad-mode Pinecone query + post-intersect"
    rather than passing the (large) ID list as a Pinecone filter
    argument.

    Order is unspecified — the caller re-ranks by vector score and
    partition (matched vs partial-data).
    """
```

SQL adapter implementation (sketch — Pythonic, SQLAlchemy 2.0):

```python
async def list_ids_for_search(self, *, location, route_filters, parsed, limit):
    async with self._session_factory() as session:
        q = select(PropertyListingModel.id).where(
            PropertyListingModel.status == PropertyStatus.ACTIVE,
        )
        # Always-applied location filters
        if location.parish:
            q = q.where(PropertyListingModel.parish == location.parish)
        if location.municipality:
            q = q.where(PropertyListingModel.municipality == location.municipality)
        if location.district:
            q = q.where(PropertyListingModel.district == location.district)

        # Route-param HARD filters (FE form) — conflict resolution: route
        # wins WHEN SET. Use `is not None` to avoid falsy-trap on Decimal('0')
        # or int(0) — `route_filters.min_price or parsed.min_price` collapses
        # an explicit ?min_price=0 to the extractor's value.
        eff_typology = (
            route_filters.typology if route_filters.typology is not None else parsed.typology
        )
        if eff_typology is not None:
            q = q.where(PropertyListingModel.typology == eff_typology.value)
        if route_filters.listing_type is not None:
            q = q.where(PropertyListingModel.listing_type == route_filters.listing_type.value)

        eff_min_price = (
            route_filters.min_price if route_filters.min_price is not None else parsed.min_price
        )
        eff_max_price = (
            route_filters.max_price if route_filters.max_price is not None else parsed.max_price
        )
        if eff_min_price is not None:
            q = q.where(
                or_(
                    PropertyListingModel.min_price.is_(None),
                    PropertyListingModel.min_price >= eff_min_price,
                )
            )
        if eff_max_price is not None:
            q = q.where(
                or_(
                    PropertyListingModel.min_price.is_(None),
                    PropertyListingModel.min_price <= eff_max_price,
                )
            )

        # ParsedQuery SOFT-HARD filters (NULL admitted).
        if parsed.min_bedrooms is not None:
            q = q.where(
                or_(
                    PropertyListingModel.num_of_bedrooms.is_(None),
                    PropertyListingModel.num_of_bedrooms >= parsed.min_bedrooms,
                )
            )
        # …same shape for min_bathrooms, area_in_m2 (gte+lte), has_pool,
        #   has_garden, has_elevator, has_parking
        # has_parking derives from parking_spaces > 0:
        if parsed.has_parking is True:
            q = q.where(
                or_(
                    PropertyListingModel.parking_spaces.is_(None),
                    PropertyListingModel.parking_spaces > 0,
                )
            )

        q = q.limit(limit)
        result = await session.execute(q)
        return [UUID(row[0]) for row in result.all()]
```

The in-memory adapter mirrors the shape (iterate, filter, slice). Both adapters return `list[UUID]`.

**Cardinality guard** — lives in `SearchListings`:

```python
async def _run_vector_query(
    self,
    *,
    vector: list[float],
    candidates: list[UUID],
    cardinality_saturated: bool,
) -> list[VectorMatch]:
    if cardinality_saturated:
        # SQL pre-filter hit the LIMIT (SEARCH_MAX_PRE_FILTER_CANDIDATES).
        # Don't bother filtering at Pinecone — over-broad ID lists hurt
        # more than they help. Run broad over the namespace, intersect
        # after.
        log.info("search.broad_mode", reason="prefilter_saturated")
        matches = await self._vector_index.query(
            vector=vector,
            filter={"status": {"eq": PropertyStatus.ACTIVE.value}},
            top_k=self._top_k * self._broad_mode_overshoot,
            namespace=self._namespace,
        )
        candidate_set = set(str(c) for c in candidates)
        return [m for m in matches if m.id in candidate_set][: self._top_k]
    elif candidates:
        # Normal mode: push the candidate IDs into the Pinecone filter.
        # NB: filter on `listing_id` (a metadata field the embedding
        # handler writes — see embedding_handler._index_metadata), NOT
        # on `id` — Pinecone's vector ID is first-class and not
        # filterable through `filter=`.
        return await self._vector_index.query(
            vector=vector,
            filter={
                "and": [
                    {"status": {"eq": PropertyStatus.ACTIVE.value}},
                    {"listing_id": {"in": [str(c) for c in candidates]}},
                ]
            },
            top_k=self._top_k,
            namespace=self._namespace,
        )
    else:
        # SQL pre-filter returned 0 — no listings match the structural
        # criteria at all. Don't bother calling Pinecone.
        return []
```

The `VectorIndex` port surface ALREADY supports `in` from ADR-013 (`{"municipality": {"in": [...]}}` is a documented example in `src/listings/domain/vector.py`). The metadata field name `listing_id` is set by phase 1's embedding handler (verified at `src/listings/adapters/workers/embedding_handler.py:139` — `"listing_id": str(row.id)`).

Settings: `SEARCH_MAX_PRE_FILTER_CANDIDATES=1000`, `SEARCH_BROAD_MODE_OVERSHOOT=4`.

#### 9. Canonical text v3 composer

`src/listings/application/services/canonical_text.py` (existing file). Add `render_v3()`:

```
TYPOLOGY: <typology.value>
CHARACTERISTICS: T<num_of_bedrooms>[, <area_in_m2>m²][, <num_of_bathrooms> casas de banho]
FEATURES: <comma-list of true booleans: piscina, jardim, elevador, garagem>
NEARBY: <comma-list of `<PoiCategory.value>@<distance_meters>m`, sorted by distance>
DESCRIPTION: <suffix-clipped agent text>
LOCATION: <parish>, <municipality>, <district>
PRICE: <min_price> EUR
```

Sections are absent when the underlying data is. NEARBY: uses **the closed `PoiCategory` value strings**, NOT the PT surface form. Distance rounded to the nearest 100m (stability — avoids hash churn on minor POI distance updates).

`render_v2` is deleted in the same change — no parallel versions in code. We re-index dev/staging once and v2 is gone. The handler unconditionally calls `render_v3`. The `LISTING_CANONICAL_TEXT_VERSION` constant lives in code (a module-level `"v3"` string) and is embedded into the hash tuple (ADR-013 §3) so a future v3→v4 bump can still distinguish old/new hashes.

#### 10. Embedding-handler metadata — unchanged

`embedding_handler._index_metadata` stays at ADR-013's V1 schema (`listing_id`, `organization_id`, `parish`, `municipality`, `district`, `listing_type`, `typology`, `status`, `price_eur`). No new fields. The structural facets (`num_of_bedrooms`, `has_pool`, etc.) live on `property_listings` and are filtered there via SQL pre-filter, not duplicated onto Pinecone metadata.

The handler-side change in this spec is **switching the composer call from `render_v2` to `render_v3`**. One line.

#### 11. `_partition_and_rank` — replaces `_reorder_by_score`

```python
@staticmethod
def _partition_and_rank(
    rows: list[PropertyListing],
    matches: list[VectorMatch],
    parsed: ParsedQuery,
) -> list[PropertyListing]:
    """Score-order with NULL rows pushed to the bottom of the page.

    A row goes into the partial bucket when at least one ParsedQuery
    criterion that was SET can't be evaluated against the row because
    the corresponding column is None. Otherwise it's in the matched
    bucket. Each bucket is internally ordered by vector cosine score.
    """
    by_id = {str(r.id): r for r in rows}
    matched: list[PropertyListing] = []
    partial: list[PropertyListing] = []
    for m in matches:
        row = by_id.get(m.id)
        if row is None:
            continue
        if _has_unevaluable_criterion(row, parsed):
            partial.append(row)
        else:
            matched.append(row)
    return matched + partial


def _has_unevaluable_criterion(row: PropertyListing, parsed: ParsedQuery) -> bool:
    if parsed.min_bedrooms is not None and row.num_of_bedrooms is None:
        return True
    if parsed.min_bathrooms is not None and row.num_of_bathrooms is None:
        return True
    if (parsed.min_area_m2 is not None or parsed.max_area_m2 is not None) \
            and row.area_in_m2 is None:
        return True
    if parsed.has_pool is True and row.has_pool is None:
        return True
    if parsed.has_garden is True and row.has_garden is None:
        return True
    if parsed.has_elevator is True and row.has_elevator is None:
        return True
    if parsed.has_parking is True and row.parking_spaces is None:
        return True
    if (parsed.min_price is not None or parsed.max_price is not None) \
            and row.min_price is None:
        return True
    return False
```

#### 12. Route handler — matched/unmatched POI composition

`src/listings/adapters/api/routes/listings.py` updates the `list_properties` handler. After `search_listings.execute(...)` returns `(rows, total, parsed)`:

```python
items = []
for prop in rows:
    image_urls = await _generate_image_urls(request, prop)
    items.append(_to_response_with_pois(
        prop,
        image_urls,
        requested_pois=parsed.nearby_pois,
    ))
```

A new `_to_response_with_pois` extends `_to_response` to populate `matched_pois` and `unmatched_pois`:

```python
def _to_response_with_pois(
    prop: PropertyListing,
    image_urls: dict[str, str],
    requested_pois: tuple[PoiCategory, ...],
) -> ListedPropertyResponse:
    base = _to_response(prop, image_urls)  # existing builder, returns ListedPropertyResponse
    if not requested_pois:
        # Structured-filter path — no POI matching applies.
        return base
    requested = {p.value for p in requested_pois}
    listing_categories = {poi.category for poi in prop.pois}
    matched_pois = [
        POIResponse(
            category=poi.category,
            name=poi.name,
            distance_meters=poi.distance_meters,
            address=poi.address,
            image_urls=poi.image_urls,
            reviews=poi.reviews,
        )
        for poi in prop.pois
        if poi.category in requested
    ]
    # Explicit ascending-distance sort. `prop.pois` from the projection
    # is in discovery order (whatever order properties emitted the POIs
    # in `build_property_snapshot`), NOT distance order. The canonical-
    # text composer sorts by (category, distance, name) for the NEARBY:
    # line — that sort doesn't propagate to the JSONB projection.
    matched_pois.sort(key=lambda p: p.distance_meters)
    unmatched_pois = sorted(requested - listing_categories)
    return base.model_copy(update={
        "matched_pois": matched_pois,
        "unmatched_pois": unmatched_pois,
    })
```

The structured-filter (q-empty) path keeps using the existing `_to_response` (no POI fields on the response — they're absent / null, see schema below).

#### 13. Properties-side: extend the POI snapshot to carry rich metadata

**Cross-context dependency landed in this spec.** The rich POI fields already live on `PropertyPoi` (the properties aggregate model — see `src/properties/domain/models/property_poi.py:54-63`), but the event payload builder in `src/properties/application/events/property_event.py:111-119` drops them on the floor:

```python
# CURRENT — only the three lean fields make it into the snapshot:
payload["pois"] = [
    {"category": poi.category.value, "name": poi.name, "distance_meters": poi.distance_meters}
    for poi in pois
]
```

Without this fix the matched-POI response surfaces only `{category, name, distance_meters}` regardless of what the projector reads — the upstream snapshot is the bottleneck. Extend the builder:

```python
# NEW — pass through the rich Place-details fields:
payload["pois"] = [
    {
        "category": poi.category.value,
        "name": poi.name,
        "distance_meters": poi.distance_meters,
        "address": poi.address,
        "image_urls": list(poi.image_urls or []),
        "reviews": poi.reviews,                # list[dict] | None
    }
    for poi in pois
]
```

This is a small change at one call site. The properties context owns the snapshot shape; this is a deliberate, documented extension to it. Tracked under the same spec since the matched-POI UX is the visible win and the change is too small to justify a separate properties-side spec.

#### 14. Widen `ListingPoi` + projection

New shape mirrors the rich `PropertyPoi` fields (matches upstream collection types — `list` not `tuple` — to avoid impedance mismatch and the unhashable-frozen-dataclass footgun):

```python
@dataclass(frozen=True, eq=True, unsafe_hash=False)
class ListingPoi:
    category: str
    name: str
    distance_meters: float
    address: str | None = None
    image_urls: list[str] = field(default_factory=list)
    reviews: list[dict] | None = None
```

`unsafe_hash=False` (and no auto-hash from `frozen=True` + `eq=True`) — explicit: `ListingPoi` is a value object but not hashable, because `list[dict]` contents would raise `TypeError` at hash time. The matched-POI composition path never hashes individual POIs (it hashes only `poi.category` strings via set comprehensions), so this is safe.

The projector (`_event_to_row` in `inmemory_property_listing_repo.py` and `property_listing_repository.py`) reads the new fields from the upstream POI snapshot payload — populated by the §13 properties-side change.

**No Alembic migration.** `property_listings.pois` is already a JSONB column and absorbs the new fields without DDL. Existing rows refresh on the next `PROPERTY_UPDATED.v1`. The canonical-text v3 backfill (§Rollout) touches every active row and writes the new POI shape as a side effect.

#### 15. Response schemas

`src/listings/adapters/api/schemas.py` adds:

```python
class POIResponse(BaseModel):
    category: str
    name: str
    distance_meters: float
    address: str | None = None
    image_urls: list[str] = []
    reviews: list[dict] | None = None


class ListedPropertyResponse(BaseModel):
    # …existing fields
    matched_pois: list[POIResponse] = []
    unmatched_pois: list[str] = []
```

Both fields default to `[]` (NOT `None`). The q-empty path doesn't populate them — they stay as the empty default and serialize as `"matched_pois": [], "unmatched_pois": []` in the JSON. The q-set path populates them in the route handler.

**Why empty lists instead of `None` + `response_model_exclude_none=True`:** `exclude_none` would strip ALL `None` fields from the response, including ADR-013 phase 2 fields like `parish`, `municipality`, `district`, `country` (which are nullable when address enrichment hasn't run). The existing integration tests at `tests/integration/test_listings.py:200-220` assert `assert key in item` for those keys — `exclude_none` would silently break BWC. Empty lists keep the schema regular: `matched_pois`/`unmatched_pois` are ALWAYS present, just empty when there's nothing to match against. ~50 bytes per response of wire noise on q-empty calls; cleaner architecturally than per-route serialization flags.

#### 16. Container wiring

Container ctor signature changes:
- `query_understanding_service` → `query_extractor: QueryExtractor | None = None`.
- Wires `SearchListings(query_extractor=…)` when extractor + embedding + vector are present. Otherwise `search_listings = None` and the route falls through.

The conftest `listing_container` fixture and the bootstrap function update accordingly.

#### 17. Bootstrap

`src/shared/entrypoints/bootstrap.py`:

```python
if settings.listings_search_enabled:
    query_extractor = LangChainQueryExtractor(
        model=settings.search_llm_model,
        openai_api_key=settings.openai_api_key,
        timeout_seconds=settings.search_llm_timeout_seconds,
        max_output_tokens=settings.search_llm_max_output_tokens,
    )
else:
    query_extractor = IdentityQueryExtractor()
```

Two new settings beyond what ADR-013 already added:

| Setting | Default | Purpose |
|---|---|---|
| `SEARCH_MAX_PRE_FILTER_CANDIDATES` | `1000` | Cap on the SQL pre-filter result. A saturated result (== cap) triggers broad-mode at the cardinality guard. |
| `SEARCH_BROAD_MODE_OVERSHOOT` | `4` | Multiplier on Pinecone `top_k` when broad-mode runs (we overshoot, then intersect with candidates). |

ADR-013's settings remain (`LISTINGS_SEARCH_ENABLED`, `SEARCH_LLM_MODEL=gpt-4o-mini`, `SEARCH_LLM_TIMEOUT_SECONDS=4.0`, `SEARCH_LLM_MAX_OUTPUT_TOKENS=200`, `VECTOR_INDEX_TOP_K=50`). The model default stays `gpt-4o-mini`.

### Test strategy

All unit test files flat under `tests/unit/listings/` (existing convention).

- **Unit** — `tests/unit/listings/test_parsed_query.py`: defaults, frozen-ness, empty construction is allowed.
- **Unit** — `tests/unit/listings/test_poi_category_contract.py`: assert `set(c.value for c in listings.PoiCategory) == set(c.value for c in properties.PoiCategory)`. Pins the closed-vocabulary alignment.
- **Unit** — `tests/unit/listings/test_langchain_query_extractor.py`: stub `_llm.ainvoke` to return canned `ParsedQuery` payloads for ~10 worked examples (the ones in the acceptance criteria). Pin negation conservatism. Pin timeout + error paths.
- **Unit** — `tests/unit/listings/test_query_for_embed_renderer.py`: pin the sectional re-rendering of `ParsedQuery` produces the canonical-text-v3 layout. Empty `ParsedQuery` with non-empty `free_text_remainder` → `DESCRIPTION: <text>` only.
- **Unit** — `tests/unit/listings/test_canonical_text_v3.py`: pin the v3 composer output for representative listings.
- **Unit** — `tests/unit/listings/test_search_listings_use_case.py`: replace the existing fail-open + filter-translation tests with structured-aware ones. New assertions: SQL pre-filter is called with the right combined filters; `asyncio.gather` runs pre-filter + embed in parallel; cardinality guard switches to broad-mode when pre-filter saturates; route-param/ParsedQuery conflict resolution; `_partition_and_rank` partitions NULL rows to the bottom of the result list; `execute` returns the 3-tuple `(rows, total, parsed)`.
- **Unit** — `tests/unit/listings/test_list_ids_for_search.py`: pin the SQL pre-filter against the in-memory repo. Every soft-hard combination, every NULL admission, every route-param-vs-ParsedQuery precedence rule, plus the saturation flag when `len(result) == limit`.
- **Integration** — `tests/integration/test_search_endpoint.py` (existing): update for the new response shape (`matched_pois` / `unmatched_pois`). Add cases covering soft-hard NULL admission (a T2 with NULL bedrooms appears at the bottom of a "T3" search; a T2 with `num_of_bedrooms=2` is excluded outright). Add a broad-mode cardinality test (seed 1100 active listings + low-selectivity query; assert the pipeline still returns top-k correctly via the intersect path).
- **Unit** — `tests/unit/properties/test_property_event_payload.py` (new file — only the sibling `test_property_event_postal_code.py` exists today): given a `Property` whose POIs carry `address`, `image_urls`, `reviews`, the emitted `build_property_snapshot` payload's `pois[i]` dict contains those three keys with the expected values. Defends against an accidental refactor that strips them out.

### Rollout

1. Land all code in one release. `LISTINGS_SEARCH_ENABLED` stays `false` (same gate, no rename).
2. Wipe the dev/staging vector namespace.
3. Run the existing `2026-05-listings-canonical-text-backfill` spec mechanism: enqueue `PROPERTY_LISTING_UPDATED.v1` for every active listing. The handler re-renders canonical text v3, computes a new hash, embeds, upserts. Metadata payload stays at ADR-013 V1 schema — no metadata-schema dance.
4. Validate offline against a manual PT query corpus (~30 queries covering the worked examples + edge cases).
5. Flip `LISTINGS_SEARCH_ENABLED=true` in staging. Eyeball latency + fallback metrics for a day. Watch the "broad mode" log line — should be rare on staging traffic.
6. Flip in production.

If we go to production before this spec ships, the rollout flips to ADR-013's parallel-namespace pattern. Pre-prod, in-place is cheaper.

## Affected files / surfaces

### New
- `src/listings/application/ports/query_extractor.py`
- `src/listings/domain/parsed_query.py`
- `src/listings/domain/poi_category.py`
- `src/listings/adapters/ai/langchain_query_extractor.py`
- `src/listings/adapters/inmemory/inmemory_query_extractor.py`
- `tests/unit/listings/test_parsed_query.py`
- `tests/unit/listings/test_poi_category_contract.py`
- `tests/unit/listings/test_langchain_query_extractor.py`
- `tests/unit/listings/test_query_for_embed_renderer.py`
- `tests/unit/listings/test_canonical_text_v3.py`
- `tests/unit/listings/test_list_ids_for_search.py`
- `tests/unit/properties/test_property_event_payload.py` — new file (no existing tests cover the `build_property_snapshot` payload shape; only `test_property_event_postal_code.py` exists for the related postal-code extraction). Pins that `address` / `image_urls` / `reviews` make it into the POI sub-payload, defending against a future refactor that strips them.

### Modified
- `src/properties/application/events/property_event.py` — extend the POI snapshot payload to carry `address`, `image_urls`, `reviews` (§13). Cross-context dependency landed in this spec because the matched-POI UX is the visible win and the change is small (3 fields added at one call site).
- `src/listings/application/use_cases/search_listings.py` — rewritten internals (extract → parallel(SQL pre-filter, embed) → cardinality-guarded ANN → hydrate → partition-and-rank). Returns 3-tuple including `ParsedQuery`.
- `src/listings/application/services/canonical_text.py` — add `render_v3`, remove `render_v2`.
- `src/listings/application/ports/repositories/property_listing_repository.py` — add `list_ids_for_search` abstract method.
- `src/listings/adapters/database/property_listing_repository.py` — implement `list_ids_for_search` against `PropertyListingModel`. Reads the new POI fields from the upstream snapshot via the projector.
- `src/listings/adapters/inmemory/inmemory_property_listing_repo.py` — implement `list_ids_for_search` (Python filter loop). Reads new POI fields from the snapshot.
- `src/listings/adapters/workers/embedding_handler.py` — canonical-text version routing only. `_index_metadata` schema unchanged.
- `src/listings/adapters/api/routes/listings.py` — unpack 3-tuple; new `_to_response_with_pois` helper composing matched/unmatched POIs; new imports for `PoiCategory` (type hint on the helper's `requested_pois` parameter) and `POIResponse`.
- `src/listings/adapters/api/schemas.py` — add `POIResponse`, `matched_pois` + `unmatched_pois` on `ListedPropertyResponse`.
- `src/listings/domain/property_listing.py` — widen `ListingPoi` to carry address/image_urls/reviews.
- `src/listings/container.py` — `query_understanding_service` → `query_extractor`.
- `src/shared/entrypoints/bootstrap.py` — wire `LangChainQueryExtractor` / `IdentityQueryExtractor`.
- `src/shared/config.py` — add `SEARCH_MAX_PRE_FILTER_CANDIDATES`, `SEARCH_BROAD_MODE_OVERSHOOT`.
- `.env.example` — append the two new settings.
- `tests/unit/listings/test_search_listings_use_case.py` — rewritten.
- `tests/unit/listings/test_inmemory_property_listing_repo.py` — POI fields in `ListingPoi` round-trip.
- `tests/unit/listings/test_search_validation.py` — no change expected.
- `tests/integration/test_search_endpoint.py` — assert the new response shape + NULL-handling behavior + broad-mode cardinality path.
- `README.md` § Listings Semantic Search Setup → §8 "Search read path" updated for the new pipeline.
- `docs/features/listings.md` — update.

### Unchanged (explicitly NOT touched by this spec)
- `src/listings/domain/vector.py` and `src/listings/application/ports/vector_index.py` — port surface keeps the ADR-013 operator set (`eq`, `in`, `gte`, `lte`, `and`). No `or` / `exists` added.
- `src/listings/adapters/vector/inmemory_index.py` and `pinecone_index.py` — no operator additions.

### Deleted
- `src/listings/application/ports/query_understanding.py`
- `src/listings/adapters/ai/langchain_query_understanding.py`
- `src/listings/adapters/inmemory/inmemory_query_understanding.py`
- `tests/unit/listings/test_query_understanding.py`

## Acceptance criteria

Each criterion phrases an **externally observable** behavior.

### Extraction
- [ ] "casa T3 com piscina perto de escola" → `ParsedQuery(typology=HOUSE, min_bedrooms=3, has_pool=True, nearby_pois=(SCHOOL,))`.
- [ ] "T2 jeitoso com varanda em Cascais" → `ParsedQuery(typology=APARTMENT, min_bedrooms=2, free_text_remainder="...jeitoso...varanda...")`. "varanda" isn't in the closed feature enum and lands in `free_text_remainder`.
- [ ] "ginásio escola supermercado" → `ParsedQuery(nearby_pois=(GYM, SCHOOL, GROCERY))`. Listing-style queries parse cleanly.
- [ ] "não preciso de piscina" → `ParsedQuery(has_pool=None)`. Negation conservatively ignored.
- [ ] "casa perto de cabeleireiro" → `ParsedQuery(typology=HOUSE, nearby_pois=(), free_text_remainder="...cabeleireiro")`. Off-vocabulary POI lands in `free_text_remainder`.
- [ ] Extractor failure → `ParsedQuery(free_text_remainder=query)`, search still returns 200.

### Hybrid retrieval (SQL pre-filter → Pinecone ID-filter)
- [ ] "T3" excludes rows with `num_of_bedrooms = 2` from the SQL pre-filter result. Integration test seeds a T2 + a T3 and asserts only the T3 ID surfaces.
- [ ] "T3" admits rows with `num_of_bedrooms IS NULL` into the SQL pre-filter result. The use case's `_partition_and_rank` then ranks them BELOW T3-matched rows. Integration test seeds a row with the column unset; asserts it appears last.
- [ ] "perto de escola" soft-signal: ranks `NEARBY: school@…` listings above silent ones but doesn't exclude (POIs aren't in the pre-filter).
- [ ] Conflict resolution: `?typology=apartment` + extracted "casa" → SQL pre-filter uses `typology='apartment'`. Asserted at the unit level by inspecting the SQLAlchemy stmt or the in-memory filter call.
- [ ] `parsed.min_price` applies when route param `min_price` is None.
- [ ] Cardinality guard: when SQL returns `>= SEARCH_MAX_PRE_FILTER_CANDIDATES`, the use case runs Pinecone in broad mode and intersects with the candidate set. Integration test seeds 1100 low-selectivity rows and asserts the response still returns the top-k correctly.
- [ ] SQL pre-filter + embed run in parallel via `asyncio.gather`. Unit test pins this deterministically (no timing math): the embed stub `await`s an `asyncio.Event` that's set by the SQL stub before the SQL stub returns. If `gather` runs the two coroutines sequentially, embed deadlocks; the test wraps `execute()` in `asyncio.wait_for(..., timeout=1.0)` so non-parallel implementations fail loudly with `TimeoutError`.

### Canonical text v3
- [ ] Composer renders a representative listing as the sectional layout in §"Canonical text v3 composer".
- [ ] Embedding-handler metadata payload unchanged from ADR-013 V1 schema (`listing_id`, `organization_id`, `parish`, `municipality`, `district`, `listing_type`, `typology`, `status`, `price_eur`).

### Response shape
- [ ] **Upstream snapshot carries the rich POI fields.** Unit test on `build_property_snapshot` at `src/properties/application/events/property_event.py:51` — given a `PropertyPoi(address="X", image_urls=["a"], reviews=[{...}])`, the emitted payload's `pois[i]` dict contains those three keys with the expected values. Verified at the properties side, not just listings, so a stray refactor on the payload builder doesn't silently regress this spec.
- [ ] `q` set + listing has `school` POI → response includes `matched_pois=[{category: "school", name, distance_meters, address, image_urls, reviews}]` and `unmatched_pois=[]`. Asserted with non-null `address` and non-empty `image_urls` to confirm the snapshot → projection → response path carries the rich fields end-to-end.
- [ ] `q` set + user asked for `gym` + listing has no gym POI → response includes `unmatched_pois=["gym"]`.
- [ ] `q` empty → response carries `"matched_pois": []` and `"unmatched_pois": []` (always present; empty defaults from the schema). No `response_model_exclude_none` flag.
- [ ] `ListedPropertyResponse` backwards-compatible with the v1 contract for q-empty calls — all existing ADR-013 phase 2 integration tests pass.
- [ ] Multiple matches per category: when a listing has 3 schools in `prop.pois` and the user asks for `SCHOOL`, all 3 surface in `matched_pois` (no dedup to nearest). Order is ascending by `distance_meters` — the route helper sorts explicitly (the projection's `prop.pois` is in discovery order, not distance order, so this sort is load-bearing). Asserted by seeding a listing with 3 schools at 1500m / 200m / 800m **in that insertion order** (NOT sorted) and checking `[p.distance_meters for p in response.matched_pois] == [200, 800, 1500]`.

### Hygiene
- [ ] `ruff check` clean, full suite green.
- [ ] README + `docs/features/listings.md` updated.
- [ ] Contract test pins `listings.PoiCategory` ⊇ `properties.PoiCategory`.

## Open questions (post-review)

- **None outstanding** — all six review decisions are now resolved:
  - Q1 (PoiCategory ownership) → inline in listings + contract test against `properties.domain.models.property_poi.PoiCategory`.
  - Q2 (NULL handling) → soft-hard via SQL `IS NULL OR …` at the pre-filter stage + app-side partition-and-rank.
  - Q3 (off-vocab POI fallback) → include surface form in `free_text_remainder`.
  - Q4 (price precedence) → route-param wins; None route-param defers to `ParsedQuery`.
  - Q5 (`min_parking_spaces`) → TODO comment; not in scope.
  - Q6 (where to filter — Pinecone metadata vs SQL pre-filter) → SQL pre-filter on `property_listings` runs in parallel with embed via `asyncio.gather`. Pinecone metadata stays at ADR-013 V1; no port-surface expansion. Cardinality guard handles broad cases.

## Out of scope follow-ups

- **`min_parking_spaces` filter** — exact-count parking ("com 2 lugares de garagem"). TODO landed on `ParsedQuery`.
- **Cross-encoder re-ranker** (ADR-014 §9). Defer until quality data justifies.
- **Personalization** (saved searches, user history). Defer.
- **Faceted result counts** ("X in Cascais, Y in Estoril, …"). Defer.
- **Polarity parsing** — "não preciso de piscina" as `has_pool=False`.
- **Multilingual extraction** — EN/DE/FR query support.

## Commits

Conventional commits, scope = `listings`:

- `feat(listings): PoiCategory closed enum + properties-side contract test`
- `feat(listings): ParsedQuery value object`
- `feat(listings): QueryExtractor port + identity adapter + LangChain adapter (replaces QueryUnderstandingService)`
- `feat(properties): emit address/image_urls/reviews in POI snapshot payload`
- `feat(listings): widen ListingPoi with address/image_urls/reviews from upstream snapshot`
- `feat(listings): list_ids_for_search on PropertyListingRepository (SQL pre-filter)`
- `feat(listings): canonical-text v3 composer + handler routing`
- `feat(listings): SearchListings rewrite — parallel pre-filter + cardinality guard + partition-and-rank`
- `feat(listings): matched/unmatched POIs on ListedPropertyResponse`
- `chore(listings): wire QueryExtractor + pre-filter settings in container + bootstrap`
- `docs(listings): update README + listings.md for the new pipeline`
