# ADR-014: Listing semantic search — structured query extraction + hybrid retrieval

**Date:** 2026-05-11
**Status:** Draft
**Relates to:** Refines ADR-013 before the search read path goes to production. ADR-013 phase 2 shipped behind a gate (`LISTINGS_SEARCH_ENABLED=false`); no production traffic. We're iterating on the search architecture in-place rather than running a parallel-namespace rollout, because there's no live system to keep callable. Replaces `QueryUnderstandingService` with `QueryExtractor`; bumps the vector-index metadata schema (`LISTING_INDEX_METADATA_V1` → `V2`); bumps the canonical-text version (`v2` → `v3`); expands the `VectorIndex` port surface with `exists` and `or`.

## Context

ADR-013 phase 2 shipped a read path (still gated off) that runs `QueryUnderstandingService.rewrite` (free-text → free-text PT canonicalization) → `EmbeddingProvider.embed` → `VectorIndex.query` with status + location + listing_type + typology + price as hard filters → DB hydrate. The pipeline works, but the architecture leaves three signals on the table:

1. **Deterministic facets are evaluated as soft signals.** The query *"casa T3 com piscina"* names three structured intents: `typology=casa`, `min_bedrooms=3`, `has_pool=true`. ADR-013 v1 hard-filters typology (when present as a route param) but routes the bedroom-count and pool intents through cosine. Cosine doesn't distinguish "the listing mentions piscina because it has one" from "the listing mentions piscina because the agent's blurb compared it favourably to a neighbour's." Hard filters do. The structural fields are already on `property_listings` (`num_of_bedrooms`, `has_pool`, `has_garden`, `has_elevator`, `area_in_m2`, `parking_spaces`) — we just don't expose them to the query side.

2. **Query side and listing side don't share an explicit structure.** The canonical-text composer renders the listing as `TYPOLOGY: ... NEARBY: ... FEATURES: ...` (`LISTING_CANONICAL_TEXT_V2`). The v1 query rewriter emits **free text** ("casa com varanda, perto de ginásio"). Cosine has to do the alignment implicitly. Aligning the two sides — both speak the same sectional vocabulary — should improve top-k quality without paying for a cross-encoder.

3. **POI categories carry surface-form noise.** A query mentioning "academia" should hit listings tagged with `gym` POIs. ADR-013 v1 leans on the LLM rewriter to normalize ("academia" → "ginásio") and on the multilingual embedder to bridge any remaining gap. Collapsing both query- and listing-side onto a **closed POI category vocabulary** (the same enum the property POI workflow uses) removes the failure mode entirely.

These are observations from the architecture, not from traffic. The search has not seen production load yet — it shipped behind `LISTINGS_SEARCH_ENABLED=false`. ADR-014 is therefore a design-from-first-principles exercise informed by ADR-013's deferred items. **Because the system is not in production, this ADR refactors in place rather than introducing a parallel `_V2` mechanism alongside the existing search.** There's nothing to keep callable; dev/staging gets re-indexed once, then we ship. The cross-encoder re-ranker that ADR-013 §6.7 / v6 sketched stays deferred — re-ranking is a quality-of-top-10 tool, and we shouldn't reach for it before exhausting the cheaper structural improvements below.

## Decision

### 1. Query understanding becomes structured extraction

**Replace** `QueryUnderstandingService.rewrite(query: str) -> str` with `QueryExtractor.extract(query: str) -> ParsedQuery`. The old port + adapters are deleted in the same change — there's no parallel mode. `ParsedQuery` is a typed value object:

| Field | Type | Source intent |
|---|---|---|
| `free_text_remainder` | `str` | The residue after extraction. Drives the embedded "soft" portion of the query. |
| `typology` | `Typology \| None` | "casa", "apartamento", "terreno", "ruína". |
| `min_bedrooms` | `int \| None` | "T2"/"T3" or "3 quartos". |
| `min_bathrooms` | `int \| None` | "2 wcs" / "2 casas de banho". |
| `min_area_m2` | `int \| None` | "pelo menos 100m²" |
| `max_area_m2` | `int \| None` | "no máximo 200m²" |
| `min_price` | `Decimal \| None` | "até 500k" / "menos de 500.000". |
| `max_price` | `Decimal \| None` | "a partir de 250k". |
| `has_pool` | `bool \| None` | "piscina". |
| `has_garden` | `bool \| None` | "jardim". |
| `has_elevator` | `bool \| None` | "elevador". |
| `has_parking` | `bool \| None` | "garagem" / "estacionamento". |
| `nearby_pois` | `list[POICategory]` | Closed enum: `school, gym, supermarket, restaurant, hospital, pharmacy, transport, beach, park, ...`. |

The LLM extracts **only what the user explicitly mentioned**. Missing fields stay `None`. No hallucination, no genre-defaults ("families want gardens" → `has_garden=True` is forbidden), no contextual inference. Same fail-open envelope as v1: extractor errors → fall back to an empty `ParsedQuery` with `free_text_remainder = query`. Search still runs, just less smart.

**Why not stay on text→text and let the embedder figure it out?** Three reasons. (a) Structured output is testable — a unit test asserts that "T3" extracts to `min_bedrooms=3` deterministically; "the rewriter produced a vibe-correct paraphrase" isn't. (b) Hard filters are cheap. (c) The LLM is more reliable at a constrained JSON output than at an open-ended canonicalization — the rewrite-v1 prompt has 8 lines of "don't do X" precisely because the model wanted to wander.

### 2. Hybrid retrieval — soft-hard filters for deterministic facets, soft signal for the rest

The vector query filter becomes the AND of three blocks:

```
filter = AND(
    # ADR-013 phase 2 filters (preserved as-is)
    status = "active",
    location filter (parish/municipality/district from the FE selector),
    structured filters from the route params (listing_type, typology, price),

    # NEW: ParsedQuery filters — emitted ONLY when the field is non-None.
    # These are "soft-hard": rows missing the column entirely (NULL on
    # the projection because the agent didn't record it) are INCLUDED
    # and ranked at the bottom of the result page. Rows that have data
    # but fail the criterion are excluded outright.
    typology IN (parsed.typology, NULL)              // see §"NULL handling"
    OR(num_of_bedrooms >= parsed.min_bedrooms, !exists(num_of_bedrooms))
    OR(num_of_bathrooms >= parsed.min_bathrooms, !exists(num_of_bathrooms))
    OR(area_in_m2 >= parsed.min_area_m2, !exists(area_in_m2))
    OR(area_in_m2 <= parsed.max_area_m2, !exists(area_in_m2))
    OR(price_eur >= parsed.min_price, !exists(price_eur))
    OR(price_eur <= parsed.max_price, !exists(price_eur))
    OR(has_pool = true, !exists(has_pool))           // when parsed.has_pool is True
    OR(has_garden = true, !exists(has_garden))       // when parsed.has_garden is True
    OR(has_elevator = true, !exists(has_elevator))   // when parsed.has_elevator is True
    OR(has_parking = true, !exists(has_parking))     // when parsed.has_parking is True
)
```

POI categories are **not** added as metadata filters — the `pois` list on `property_listings` is a JSONB list of `{category, name, distance_meters, address, image_urls, reviews}`, and turning that into N booleans on the vector metadata explodes the metadata size and the per-category cardinality. Instead, **POIs become a soft signal in the embedded query text** (see §3 — canonical text v3 NEARBY: line) AND drive a per-result match/unmatch enrichment of the response payload (see §8 — POI matching response shape).

**Conflict resolution between route params and `ParsedQuery`:** the user's structured filters (FE form) take precedence over LLM-extracted ones for the same field, *except* when the route param is `None` and `ParsedQuery` has a value. Concrete rule: if a route param is set (e.g. `?typology=apartment`) and `ParsedQuery.typology` is also set (e.g. extracted "casa" from the query text), the route param wins. If the route param is None (e.g. the FE has no free-text price input), the `ParsedQuery` value applies. Rationale: form input is an explicit hard intent; extracted text is an inferred intent — and the user shouldn't have to fight their own form, but should benefit from the extractor when the form doesn't cover the dimension.

### 2a. NULL handling — soft-hard filters via `OR(criterion, !exists(field))`

This is the architecturally load-bearing nuance. The structural fields on `property_listings` are *nullable* — agents may publish a listing without filling in `num_of_bedrooms` if they didn't bother. A strict `gte` filter excludes those rows. We want them **included at the bottom of the result page** so the user still sees them — they might be the right match, the data is just missing — but listings that confirmed they satisfy the criterion rank above listings whose match status is unknown.

Two-layer implementation:

1. **At the vector index**: each `gte`/`lte`/`eq` clause from `ParsedQuery` is wrapped in `OR(criterion, !exists(field))`. This requires expanding the `VectorIndex` port surface to include `or` composition + an `exists` operator. Pinecone supports both natively (`$or`, `$exists`); the in-memory adapter gains the same. The port doc updates accordingly.

2. **At the use case post-hydrate**: `SearchListings._reorder_by_score` becomes `_reorder_by_match_then_score`. Rows are partitioned into two buckets:
   - **Matched bucket** — every `ParsedQuery` criterion the row was tested against either passed or didn't apply (the criterion wasn't set). These rows rank by cosine, top first.
   - **Partial-data bucket** — at least one `ParsedQuery` criterion couldn't be evaluated against the row because the underlying column was NULL. These rank by cosine *after* every matched row.

The partition key is computed at hydrate time by looking at the row's columns against the non-None fields on `ParsedQuery`. No second Pinecone query, no extra metadata-key dance — the data we need is already on the hydrated `PropertyListing`.

Pagination applies over the concatenation: matched rows first, partial-data rows second. `total` = `len(matched) + len(partial)` (mirroring v1's "Pinecone count survived ACTIVE hydrate" semantic).

This requires expanding the vector-index metadata schema to **`LISTING_INDEX_METADATA_V2`** (`embedding_handler._index_metadata`), adding the seven fields below to whatever v1 already carries (`listing_id`, `organization_id`, `parish`, `municipality`, `district`, `listing_type`, `typology`, `status`, `price_eur`):

| New field | Source on `PropertyListing` | Filter operator(s) |
|---|---|---|
| `num_of_bedrooms` int | `num_of_bedrooms` | `gte` |
| `num_of_bathrooms` int | `num_of_bathrooms` | `gte` |
| `area_in_m2` int | `area_in_m2` | `gte` / `lte` |
| `has_pool` bool | `has_pool` | `eq` |
| `has_garden` bool | `has_garden` | `eq` |
| `has_elevator` bool | `has_elevator` | `eq` |
| `has_parking` bool | `parking_spaces is not None and parking_spaces > 0` | `eq` |

Pinecone's metadata 40KB-per-vector cap is not a concern at this fanout — the schema stays well under 200 bytes per vector.

### 3. Canonical text v3 — sectional structure aligned with the extraction schema

Bump `LISTING_CANONICAL_TEXT_V2` to `LISTING_CANONICAL_TEXT_V3`. The composer renders the listing as:

```
TYPOLOGY: casa
CHARACTERISTICS: T3, 120m², 2 casas de banho
FEATURES: piscina, jardim, garagem, elevador
NEARBY: school@500m, gym@800m, supermarket@1200m
DESCRIPTION: <free text from the agent, suffix-clipped to LISTING_DESCRIPTION_MAX_CHARS>
LOCATION: <parish>, <municipality>, <district>
PRICE: 450000 EUR
```

Distinct from v2 (which mixed POIs and features into less-structured lines and rendered POIs by their PT surface form). Two shifts:

- **NEARBY: uses the closed POI category vocabulary**, not the PT surface form ("escola"). Distance is in metres, lowercase tokens. This makes the listing side speak the same language as `ParsedQuery.nearby_pois`.
- **CHARACTERISTICS: bundles typology-adjacent numeric facets** (bedroom count, area, bathroom count) on one line, separated from boolean amenities on FEATURES:. The same separation appears on the query side when ParsedQuery is re-rendered as a sectional string (§4).

### 4. The query embedding mirrors canonical-text v3

After extraction, the **embedded query** is the `ParsedQuery` re-rendered as a sectional string using the same vocabulary as the canonical text. For the query *"casa T3 com piscina perto de escola"*:

```
TYPOLOGY: casa
CHARACTERISTICS: T3
FEATURES: piscina
NEARBY: school
```

Sections the user didn't mention are absent. The cosine then compares **section-by-section similarity** implicitly — the model sees the same shape on both sides and aligns more cleanly than `"free-text query" vs "sectioned canonical text"`.

`free_text_remainder` from `ParsedQuery` is appended as a free-form `DESCRIPTION:` section to capture anything the structured extraction missed ("perto da praia", "com vista", etc. — softer intents that don't fit the closed enums). DESCRIPTION: is the catch-all.

### 5. POI category vocabulary

POI categories are pulled from a closed enum living in the properties context (shared via the snapshot the listings projector consumes). The full list is owned by `properties` (the POI auto-discovery workflow defines it); listings inlines a mirror enum (decision tracked in the implementation spec — review settled on "inline for now + contract test" to keep the cross-context boundary clean). The closed-vocabulary commitment is the architectural decision — the specific enum members are an implementation detail.

Surface-form normalization happens **at extraction time** (the LLM is prompted with the closed enum and asked to map surface forms onto it: "academia" → `gym`, "primária" → `school`, "talho" → `food_shop`). This collapses synonym mismatches that v1 relied on the embedder to bridge.

### 6. Re-indexing strategy

The canonical-text bump (`v2` → `v3`) invalidates every cached `embedding_text_hash` — the existing hash-dedup mechanism (ADR-013 §3) treats hashes as `(text_version, text)` tuples. The metadata schema bump (`V1` → `V2`) invalidates every indexed metadata payload — Pinecone's `update_metadata` would patch in place, but a fresh re-upsert is simpler and the embedding handler's hash mismatch triggers a full upsert anyway.

**Because the search isn't in production, there's no parallel-namespace dance.** The plan is:

1. Wipe the existing dev/staging vector namespace (nothing depends on it — search is gated off).
2. Bump `LISTING_CANONICAL_TEXT_VERSION` to `v3` and `LISTING_INDEX_METADATA_VERSION` to `V2` in code. Same release.
3. Run the existing `listings-canonical-text-backfill` spec mechanism: enqueue `PROPERTY_LISTING_UPDATED.v1` for every active listing. The handler re-renders v3, re-computes the hash, re-embeds, upserts into the (same) namespace with the new metadata schema.
4. Flip `LISTINGS_SEARCH_ENABLED=true` once the backfill drains and a manual query corpus passes.

If we go to production *with* the search dark, then later decide to bump the schemas again, we'll need ADR-013's parallel-namespace pattern. For now, the system is malleable enough to refactor in place.

### 7. Latency budget

| Stage | ADR-013 budget | This ADR's budget |
|---|---|---|
| Query understanding (LLM) | 300ms p95 (free-text rewrite) | 400ms p95 (structured output adds ~100ms) |
| EmbeddingProvider.embed | 150ms p95 | 150ms p95 (unchanged) |
| VectorIndex.query | 100ms p95 | 100ms p95 (richer filter but Pinecone's metadata filter is O(1) per clause) |
| DB hydrate | 50ms p95 | 50ms p95 |
| **Total p95** | **600ms** | **700ms** |

Still under the 800ms end-to-end target. The structured-output penalty is small because `gpt-4o-mini` constrained generation against a Pydantic schema is fast — the model writes JSON it already knew the shape of.

### 8. Response shape — matched + unmatched POIs per result

When `q` is set, the route handler carries `parsed.nearby_pois` (the POI categories the user explicitly asked for) into response composition. For each returned listing, the response splits the listing's POIs into two buckets and exposes both:

```jsonc
{
  "id": "…",
  "typology": "house",
  "characteristics": { … },
  "matched_pois": [
    {
      "category": "school",
      "name": "Escola Básica de Cascais",
      "distance_meters": 480,
      "address": "Rua das Flores, 12, Cascais",
      "image_urls": ["https://…/photo1.jpg", "https://…/photo2.jpg"],
      "reviews": [ { … } ]
    }
  ],
  "unmatched_pois": ["gym"],
  // …existing fields
}
```

- **`matched_pois`** — listings POIs whose category appears in `parsed.nearby_pois`. Full data: category, name, distance_meters, address, image_urls, reviews (the rich metadata recently added via spec `2026-05-poi-rich-metadata`). The FE renders them as illustrative chips next to the listing card.
- **`unmatched_pois`** — categories from `parsed.nearby_pois` that DIDN'T match any POI on the listing. Plain category strings. The FE renders them as "you asked for: gym (not nearby)" so the user can see why a result was ranked where it was.

When `q` is empty, both arrays are absent from the response (or empty — schema decision in the spec). The structured-filter path doesn't have a POI intent to match against.

Implications:
- `ListingPoi` (currently `{category, name, distance_meters}`) is widened to include the rich fields. The listings projector consumes them from the `PROPERTY_*.v1` snapshot (the properties context already carries them on `PropertyPoi`).
- A new `POIResponse` schema in `listings/adapters/api/schemas.py`.
- The route handler signature for response composition gains an optional `requested_pois: tuple[PoiCategory, ...]` parameter; defaults to `()` (= structured-filter path).

### 9. Iteration plan

- **This ADR** — `QueryExtractor` + `LISTING_INDEX_METADATA_V2` + `LISTING_CANONICAL_TEXT_V3` + hybrid retrieval + matched/unmatched POI response.
- **Next (deferred)** — Cross-encoder re-ranker on top-50 → top-10 against the raw query (ADR-013 §6.7). Reach for this only when retrieval-quality data shows hybrid alone is insufficient.
- **Later (deferred)** — Personalization (saved searches, history feedback into ranking), multi-signal scoring (recency, popularity), faceted result counts ("X listings in Cascais, Y in Estoril, …").

## Consequences

**Positive:**
- Deterministic facets are evaluated deterministically. A query mentioning "T3" excludes T1s instead of down-ranking them. Concretely: if a user says "casa T3 com piscina perto de escola", the result set is `WHERE typology='casa' AND num_of_bedrooms >= 3 AND has_pool = true`, then ANN-ranked by the soft "perto de escola" signal. No more T2-with-a-great-description outranking a less-described T3.
- Sectional alignment between query and listing should lift top-k quality without paying for a re-ranker.
- POI surface-form noise collapses onto a closed vocabulary.
- Structured extraction is unit-testable in a way text-rewriting never was. "T3" → `min_bedrooms=3` is a falsifiable assertion against worked examples.
- The route handler stays simple — the heavy lifting moves into a single replaceable use case (`SearchListings`, rewritten in place) behind a port.

**Negative:**
- Re-indexing every staged listing once. Free in dev; minor cost in staging. Mitigated by the backfill spec mechanism the canonical-text-backfill spec established.
- Adds an LLM call surface that must be reliable enough to extract correctly under load. Mitigated by the same fail-open envelope ADR-013 established — extractor errors degrade to "empty `ParsedQuery`, embed the raw query as DESCRIPTION:".
- The vector metadata size grows by ~7 fields per vector. Still well under Pinecone's 40KB cap.
- Expanding the `VectorIndex` port surface with `or` + `exists` is more surface to keep adapter-portable. The in-memory adapter is trivial; future adapters (turbopuffer/Qdrant/Weaviate) MUST also support both operators. Documented as part of the port contract.
- Widening `ListingPoi` from 3 fields to 6 grows the projection payload. Mitigated by the fact that the rich fields are already on the upstream snapshot (no new upstream work).

**Risks:**
- Over-extraction. The LLM might pull `has_pool=true` from a query mentioning a pool *negatively* ("não preciso de piscina"). Mitigated by prompt design ("treat negation conservatively — return null, not false") + a regression test on a negation corpus.
- Under-extraction. The LLM might miss "T3" and route the bedroom intent through cosine. Mitigated by extractor unit tests with worked examples; failures here degrade ranking but don't break correctness.
- Soft-hard filters can confuse users. A T2 with NULL `num_of_bedrooms` will appear (at the bottom) in a "T3" search — surprising if the user expected strict exclusion. Acceptable trade-off because the alternative (excluding NULL outright) is worse: missing-data listings would never surface in any structured search until an agent backfilled the column.

## Sources

- ADR-013 (foundation): `docs/adr/013-listing-semantic-search.md`
- v1 read-path spec (shipped): `.claude/specs/archive/2026-05-listing-semantic-search-read-path.md`
- v1 indexing spec (shipped): `.claude/specs/archive/2026-05-listing-semantic-search.md`
- Implementation spec for this ADR: `.claude/specs/active/2026-05-listing-search-structured-extraction.md`
