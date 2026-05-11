# Listing search — structured query extraction + hybrid retrieval (ADR-014)

**Status:** draft (review pending)
**Owner:** Peter
**Created:** 2026-05-11
**ADR:** [014-structured-query-extraction-and-hybrid-retrieval](../../docs/adr/014-structured-query-extraction-and-hybrid-retrieval.md)

## Problem

ADR-013 phase 2 (shipped 2026-05-11, gated off) routes deterministic facets named in the query (typology, T2/T3 bedroom counts, has_pool, has_garden, POI categories) through cosine even though the structural data exists on `property_listings` and could hard-filter at the vector layer. The search isn't in production yet, so this spec **refactors the search in place** — replacing `QueryUnderstandingService` with `QueryExtractor`, bumping canonical-text v2→v3, bumping vector-index metadata V1→V2, expanding the `VectorIndex` port surface with `exists`/`or`, and enriching the response with matched/unmatched POI buckets per result. No parallel gate, no parallel namespace, no v1 callable side-by-side — we re-index dev/staging once and replace the wiring outright.

Concretely: a query *"casa T3 com piscina perto de escola"* today gets embedded as one vector and cosine-ranked against listings whose canonical text mentions piscina, T3, casa, school *somewhere*. A T2 with a strong "piscina" description can outrank a T3 with a sparser description. After this spec, the same query:

1. Extracts to `ParsedQuery(typology=HOUSE, min_bedrooms=3, has_pool=True, nearby_pois=(SCHOOL,))`.
2. Hard-filters on the structural columns (with NULL-rows softly admitted at the bottom of the page — see §"NULL handling").
3. Embeds the residue as a sectional canonical-text-v3-shaped string for cosine ranking.
4. Returns matched POIs (the listing's `school` POI with full data — name, distance, address, image_urls, reviews) and unmatched POIs (categories the user asked for that this listing doesn't have nearby).

## Goal

`GET /api/v1/listings/properties?q=…&parish=…` runs the new pipeline when `LISTINGS_SEARCH_ENABLED=true` (same gate as before — no `_V2` suffix).

1. **Extract**: LLM parses the query into `ParsedQuery`. Fail-open on extractor error → `ParsedQuery(free_text_remainder=query)`.
2. **Embed**: render `ParsedQuery` as a sectional canonical-text-v3-shaped string, embed.
3. **ANN**: vector query with the AND of ADR-013 location/route-param filters + new soft-hard filters from `ParsedQuery` (each wrapped in `OR(criterion, !exists(field))`). Top-k.
4. **Hydrate**: same `list_by_ids` path. Partition rows into matched-bucket / partial-data-bucket. Sort within each by cosine. Concatenate.
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
- `src/listings/adapters/ai/langchain_query_extractor.py` — LangChain `with_structured_output(ParsedQuery)` adapter.
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

`src/listings/adapters/ai/langchain_query_extractor.py`. Structured output against `gpt-4o-mini`. System prompt:

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

1. Extract. Fail-open: `ParsedQuery(free_text_remainder=query)` on exception.
2. Render `ParsedQuery` as the canonical-text-v3-shaped embed string via `_render_query_for_embed`.
3. Embed. Fail-open to `_relational_fallback`.
4. `_build_filter` (replaced) produces an AND-clause with `OR(criterion, !exists(field))` wrappers on `ParsedQuery` clauses (§"NULL handling" below).
5. `vector_index.query`. Fail-open to `_relational_fallback`.
6. `list_by_ids` hydrate.
7. `_partition_and_rank` (replaces `_reorder_by_score`): rows where every set `ParsedQuery` criterion was evaluatable against non-NULL columns → matched bucket. Rows where ≥1 criterion couldn't be evaluated (NULL on the column) → partial bucket. Each bucket ranked by cosine. Concatenate.
8. Paginate over the concatenation.
9. Return `(rows, total, parsed)`.

The route handler (§13) updates its call site to unpack the new 3-tuple.

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

Empty `ParsedQuery` yields an empty string. The use case treats that as "embed the raw query as DESCRIPTION:" (a tiny guard at the top of `_render_query_for_embed`).

#### 8. `_build_filter` — replaced with soft-hard clauses

```python
@staticmethod
def _build_filter(
    location: LocationFilter,
    filters: PropertyFilters,     # route-param filters (FE form)
    parsed: ParsedQuery,          # LLM-extracted filters
) -> VectorFilter:
    clauses: list[dict] = [{"status": {"eq": PropertyStatus.ACTIVE.value}}]

    # Location (unchanged from ADR-013).
    if location.parish:
        clauses.append({"parish": {"eq": location.parish.lower().strip()}})
    # …municipality, district

    # Conflict resolution: route-param wins over ParsedQuery for the
    # same field, BUT a None route-param defers to ParsedQuery (FE may
    # not have a corresponding input).
    effective_typology = filters.typology or parsed.typology
    if effective_typology is not None:
        clauses.append({"typology": {"eq": effective_typology.value}})

    if filters.listing_type is not None:
        clauses.append({"listing_type": {"eq": filters.listing_type.value}})

    eff_min_price = filters.min_price or parsed.min_price
    eff_max_price = filters.max_price or parsed.max_price
    if eff_min_price is not None:
        clauses.append(_soft_hard("price_eur", "gte", float(eff_min_price)))
    if eff_max_price is not None:
        clauses.append(_soft_hard("price_eur", "lte", float(eff_max_price)))

    # ParsedQuery-only filters (no FE-form sibling).
    if parsed.min_bedrooms is not None:
        clauses.append(_soft_hard("num_of_bedrooms", "gte", parsed.min_bedrooms))
    if parsed.min_bathrooms is not None:
        clauses.append(_soft_hard("num_of_bathrooms", "gte", parsed.min_bathrooms))
    if parsed.min_area_m2 is not None:
        clauses.append(_soft_hard("area_in_m2", "gte", parsed.min_area_m2))
    if parsed.max_area_m2 is not None:
        clauses.append(_soft_hard("area_in_m2", "lte", parsed.max_area_m2))
    if parsed.has_pool is True:
        clauses.append(_soft_hard("has_pool", "eq", True))
    if parsed.has_garden is True:
        clauses.append(_soft_hard("has_garden", "eq", True))
    if parsed.has_elevator is True:
        clauses.append(_soft_hard("has_elevator", "eq", True))
    if parsed.has_parking is True:
        clauses.append(_soft_hard("has_parking", "eq", True))

    return {"and": clauses}


def _soft_hard(field: str, op: str, value) -> dict:
    """Each ParsedQuery clause becomes OR(criterion, !exists(field)) so
    NULL rows are admitted (they'll rank at the bottom; see
    SearchListings._partition_and_rank). Architectural rationale:
    ADR-014 §"NULL handling"."""
    return {"or": [
        {field: {op: value}},
        {field: {"exists": False}},
    ]}
```

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

Drop `render_v2` and the `LISTING_CANONICAL_TEXT_VERSION="v2"` setting once v3 is wired. No parallel versions in code — we re-index dev/staging once and v2 is gone.

#### 10. `LISTING_INDEX_METADATA_V2` — embedding handler

`embedding_handler._index_metadata` adds the seven new fields from ADR-014 §2:

```python
def _index_metadata(row: PropertyListing) -> dict:
    raw = {
        # …existing v1 fields (listing_id, organization_id, parish,
        # municipality, district, listing_type, typology, status, price_eur)
        "num_of_bedrooms": row.num_of_bedrooms,
        "num_of_bathrooms": row.num_of_bathrooms,
        "area_in_m2": row.area_in_m2,
        "has_pool": row.has_pool,
        "has_garden": row.has_garden,
        "has_elevator": row.has_elevator,
        "has_parking": (
            row.parking_spaces is not None and row.parking_spaces > 0
        ) if row.parking_spaces is not None else None,
    }
    return {k: v for k, v in raw.items() if v is not None}
```

None-values are dropped (consistent with the existing v1 convention). That's what makes `OR(criterion, !exists(field))` work — `exists: false` matches because the key is genuinely absent on those vectors.

#### 11. `VectorIndex` port — `exists` operator + `or` composition

ADR-014 §2a load-bearing change. Update `src/listings/domain/vector.py` documentation:

```python
"""
Operators at the port surface: `eq`, `in`, `gte`, `lte`, `exists`.
Composition keys: `and`, `or`.
"""
```

Update both adapters:
- `src/listings/adapters/vector/inmemory_index.py` — extend `_matches_filter` to support `or` (recursive) and `exists` (compare presence of key in metadata).
- `src/listings/adapters/vector/pinecone_index.py` — extend `_translate_filter` to emit `$or` and `$exists` against Pinecone's Mongo-style filter syntax.

#### 12. `_partition_and_rank` — replaces `_reorder_by_score`

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

#### 13. Route handler — matched/unmatched POI composition

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
    unmatched_pois = sorted(requested - listing_categories)
    return base.model_copy(update={
        "matched_pois": matched_pois,
        "unmatched_pois": unmatched_pois,
    })
```

The structured-filter (q-empty) path keeps using the existing `_to_response` (no POI fields on the response — they're absent / null, see schema below).

#### 14. Widen `ListingPoi` + projection

Current shape: `{category, name, distance_meters}`. New shape mirrors the rich `PropertyPoi` fields:

```python
@dataclass(frozen=True)
class ListingPoi:
    category: str
    name: str
    distance_meters: float
    address: str | None = None
    image_urls: tuple[str, ...] = ()
    reviews: tuple[dict, ...] = ()
```

The projector (`_event_to_row` in `inmemory_property_listing_repo.py` and `property_listing_repository.py`) reads the new fields from the upstream POI snapshot payload — properties already carries them since the `2026-05-poi-rich-metadata` spec. No upstream change required.

Migration: a single Alembic migration to widen `property_listings.pois` (it's already a JSONB column — no schema migration needed at the column level; the projector starts writing the new fields and existing rows get refreshed on the next `PROPERTY_UPDATED.v1`).

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
    matched_pois: list[POIResponse] | None = None
    unmatched_pois: list[str] | None = None
```

Both fields default to `None` (omitted from JSON via `model_dump(exclude_none=True)`). When `q` is empty, neither field is set; when `q` is set, both are present (possibly as empty lists if the listing has no POIs in the requested categories and the user requested no categories).

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

No new settings beyond what ADR-013 already added (`LISTINGS_SEARCH_ENABLED`, `SEARCH_LLM_MODEL=gpt-4o-mini`, `SEARCH_LLM_TIMEOUT_SECONDS=4.0`, `SEARCH_LLM_MAX_OUTPUT_TOKENS=200`, `VECTOR_INDEX_TOP_K=50`). The model default stays `gpt-4o-mini` per the ADR-013 resolution.

### Test strategy

All unit test files flat under `tests/unit/listings/` (existing convention).

- **Unit** — `tests/unit/listings/test_parsed_query.py`: defaults, frozen-ness, empty construction is allowed.
- **Unit** — `tests/unit/listings/test_poi_category_contract.py`: assert `set(c.value for c in listings.PoiCategory) == set(c.value for c in properties.PoiCategory)`. Pins the closed-vocabulary alignment.
- **Unit** — `tests/unit/listings/test_langchain_query_extractor.py`: stub `_llm.ainvoke` to return canned `ParsedQuery` payloads for ~10 worked examples (the ones in the acceptance criteria). Pin negation conservatism. Pin timeout + error paths.
- **Unit** — `tests/unit/listings/test_query_for_embed_renderer.py`: pin the sectional re-rendering of `ParsedQuery` produces the canonical-text-v3 layout. Empty `ParsedQuery` with non-empty `free_text_remainder` → `DESCRIPTION: <text>` only.
- **Unit** — `tests/unit/listings/test_canonical_text_v3.py`: pin the v3 composer output for representative listings.
- **Unit** — `tests/unit/listings/test_search_listings_use_case.py`: replace the existing fail-open + filter-translation tests with structured-aware ones. New assertions: `_build_filter` emits `or/exists`-wrapped clauses for each `ParsedQuery` field; route-param/ParsedQuery conflict resolution; `_partition_and_rank` partitions NULL rows to the bottom of the result list; `execute` returns the 3-tuple `(rows, total, parsed)`.
- **Unit** — `tests/unit/listings/test_index_metadata_v2.py`: pin the new metadata payload matches the schema for representative `PropertyListing` rows. None-values dropped consistently.
- **Unit** — `tests/unit/listings/adapters/test_inmemory_vector_index.py`: extend with cases for the new `or` and `exists` operators.
- **Unit** — `tests/unit/listings/adapters/test_pinecone_filter_translation.py`: pin `$or` / `$exists` translation (a small offline test — no live Pinecone).
- **Integration** — `tests/integration/test_search_endpoint.py` (existing): update for the new response shape (`matched_pois` / `unmatched_pois`). Add cases covering soft-hard NULL admission (a T2 with NULL bedrooms appears at the bottom of a "T3" search; a T2 with `num_of_bedrooms=2` is excluded outright).

### Rollout

1. Land all code in one release. `LISTINGS_SEARCH_ENABLED` stays `false` (same gate, no rename).
2. Wipe the dev/staging vector namespace.
3. Run the existing `2026-05-listings-canonical-text-backfill` spec mechanism: enqueue `PROPERTY_LISTING_UPDATED.v1` for every active listing. The handler re-renders canonical text v3, computes a new hash, embeds, upserts with `LISTING_INDEX_METADATA_V2` payload.
4. Validate offline against a manual PT query corpus (~30 queries covering the worked examples + edge cases).
5. Flip `LISTINGS_SEARCH_ENABLED=true` in staging. Eyeball latency + fallback metrics for a day.
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
- `tests/unit/listings/test_index_metadata_v2.py`
- `tests/unit/listings/adapters/test_pinecone_filter_translation.py`

### Modified
- `src/listings/application/use_cases/search_listings.py` — rewritten internals (extract → embed → ANN with soft-hard filters → hydrate → partition-and-rank). Returns 3-tuple including `ParsedQuery`.
- `src/listings/application/services/canonical_text.py` — add `render_v3`, remove `render_v2`.
- `src/listings/adapters/workers/embedding_handler.py` — `_index_metadata` schema v2.
- `src/listings/adapters/api/routes/listings.py` — unpack 3-tuple; new `_to_response_with_pois` helper composing matched/unmatched POIs.
- `src/listings/adapters/api/schemas.py` — add `POIResponse`, `matched_pois` + `unmatched_pois` on `ListedPropertyResponse`.
- `src/listings/adapters/vector/inmemory_index.py` — add `or` + `exists`.
- `src/listings/adapters/vector/pinecone_index.py` — add `or` + `exists`.
- `src/listings/domain/vector.py` — extend docstring; new operators in port surface.
- `src/listings/domain/property_listing.py` — widen `ListingPoi` to carry address/image_urls/reviews.
- `src/listings/adapters/database/property_listing_repository.py` + `inmemory/inmemory_property_listing_repo.py` — projector reads the new POI fields from the upstream snapshot.
- `src/listings/container.py` — `query_understanding_service` → `query_extractor`.
- `src/shared/entrypoints/bootstrap.py` — wire `LangChainQueryExtractor` / `IdentityQueryExtractor`.
- `tests/unit/listings/test_search_listings_use_case.py` — rewritten.
- `tests/unit/listings/test_inmemory_property_listing_repo.py` — POI fields in `ListingPoi` round-trip.
- `tests/unit/listings/test_search_validation.py` — no change expected.
- `tests/integration/test_search_endpoint.py` — assert the new response shape + NULL-handling behavior.
- `README.md` § Listings Semantic Search Setup → §8 "Search read path" updated for the new pipeline.
- `docs/features/listings.md` — update.

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

### Hybrid retrieval
- [ ] "T3" excludes vectors with `num_of_bedrooms = 2`. Integration test seeds a T2 + a T3 and asserts only the T3 returns.
- [ ] "T3" admits vectors with `num_of_bedrooms IS NULL` but ranks them BELOW T3-matched rows. Same integration test seeds a row with the column unset; asserts it appears last.
- [ ] "perto de escola" soft-signal: ranks `NEARBY: school@…` listings above silent ones but doesn't exclude.
- [ ] Conflict resolution: `?typology=apartment` + extracted "casa" → filter uses `typology=apartment`. Asserted by inspecting the filter sent to the (stub) vector index.
- [ ] `parsed.min_price` applies when route param `min_price` is None.

### Canonical text v3 + index metadata V2
- [ ] Composer renders a representative listing as the sectional layout in §"Canonical text v3 composer".
- [ ] `_index_metadata` includes all seven new fields when the source row has them; drops them when NULL.
- [ ] `OR(criterion, !exists(field))` round-trips through the in-memory adapter (admits both matched + missing-metadata rows).

### Response shape
- [ ] `q` set + listing has `school` POI → response includes `matched_pois=[{category: "school", name, distance_meters, address, image_urls, reviews}]` and `unmatched_pois=[]`.
- [ ] `q` set + user asked for `gym` + listing has no gym POI → response includes `unmatched_pois=["gym"]`.
- [ ] `q` empty → response has neither `matched_pois` nor `unmatched_pois` (omitted by `exclude_none`).
- [ ] `ListedPropertyResponse` backwards-compatible with the v1 contract for q-empty calls — all existing ADR-013 phase 2 integration tests pass.

### Hygiene
- [ ] `ruff check` clean, full suite green.
- [ ] README + `docs/features/listings.md` updated.
- [ ] Contract test pins `listings.PoiCategory` ⊇ `properties.PoiCategory`.

## Open questions (post-review)

- **None outstanding from review #1** — all five open questions from the draft are now resolved:
  - Q1 (PoiCategory ownership) → inline in listings + contract test.
  - Q2 (NULL handling) → soft-hard via `OR(criterion, !exists(field))` + app-side partition-and-rank.
  - Q3 (off-vocab POI fallback) → include surface form in `free_text_remainder`.
  - Q4 (price precedence) → route-param wins; None route-param defers to `ParsedQuery`.
  - Q5 (`min_parking_spaces`) → TODO comment; not in scope.

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
- `feat(listings): VectorIndex port supports or + exists (in-memory + Pinecone adapters)`
- `feat(listings): canonical-text v3 composer + LISTING_INDEX_METADATA_V2 in embedding handler`
- `feat(listings): widen ListingPoi with address/image_urls/reviews from upstream snapshot`
- `feat(listings): SearchListings rewrite — soft-hard hybrid retrieval + partition-and-rank`
- `feat(listings): matched/unmatched POIs on ListedPropertyResponse`
- `chore(listings): wire QueryExtractor in container + bootstrap`
- `docs(listings): update README + listings.md for the new pipeline`
