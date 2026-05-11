# ADR-014: Listing semantic search — structured query extraction + hybrid retrieval

**Date:** 2026-05-11
**Status:** Draft
**Relates to:** Refines ADR-013 before the search read path goes to production. ADR-013 phase 2 shipped behind a gate (`LISTINGS_SEARCH_ENABLED=false`); no production traffic. We're iterating on the search architecture in-place rather than running a parallel-namespace rollout, because there's no live system to keep callable. Replaces `QueryUnderstandingService` with `QueryExtractor`; introduces a **SQL pre-filter** that narrows the candidate set on `property_listings` before the vector query (replacing what would otherwise be a metadata-schema bump); bumps the canonical-text version (`v2` → `v3`). The `VectorIndex` port surface is unchanged.

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

### 2. Hybrid retrieval — SQL pre-filter on `property_listings`, then vector search

Rather than push deterministic-facet filtering down to Pinecone metadata (which would require duplicating the structural columns onto every vector and maintaining their consistency via the embedding handler's `update_metadata` path), the architecture **filters at the database first** and passes the resulting candidate IDs to Pinecone as a vector-ID filter.

The flow:

```
GET /api/v1/listings/properties?q=…&parish=…
   │
   ▼
 normalize_query  →  validate_location_for_search  →  QueryExtractor.extract  ⇒ parsed
   │
   ▼
 ┌──────────────────────────────────────────┐
 │  Run these two stages IN PARALLEL via    │
 │  asyncio.gather:                         │
 │                                          │
 │  (a) SQL pre-filter on property_listings │
 │      WHERE status='active'               │
 │        AND <location clauses>            │
 │        AND <route-param hard filters>    │
 │        AND <ParsedQuery soft-hard        │
 │             clauses, NULL-OR-IS-NULL>    │
 │      LIMIT MAX_PRE_FILTER_CANDIDATES     │
 │      (1000)                              │
 │                                          │
 │      → list[UUID] of candidate IDs       │
 │                                          │
 │  (b) embed(_render_query_for_embed(parsed))│
 │      → list[float]                       │
 └──────────────────────────────────────────┘
   │
   ▼
 cardinality guard:
   if len(candidates) <= MAX_VECTOR_ID_FILTER (1000):
       matches = pinecone.query(
           vector,
           filter={"id": {"in": candidate_ids}, "status": {"eq": "active"}},
           top_k=top_k,
       )
   elif len(candidates) > MAX_PRE_FILTER_CANDIDATES:
       # Pre-filter hit the LIMIT — too broad to push the ID list
       # down. Run Pinecone over the namespace and intersect after.
       matches = pinecone.query(
           vector,
           filter={"status": {"eq": "active"}},
           top_k=top_k * 4,   # overshoot to survive intersection
       )
       matches = [m for m in matches if m.id in set(candidates)][:top_k]
   else:
       # Same fall-through as the "too broad" arm for cardinalities
       # in the gap. Logged at INFO for tuning.
       …
   │
   ▼
 list_by_ids hydrate (filters to status='active' at SQL — defense in depth)
   │
   ▼
 _partition_and_rank: matched rows (every ParsedQuery criterion evaluable)
                      first, partial-data rows (≥1 criterion NULL) second
   │
   ▼
 paginate over the concatenation, compose response
```

**Key implications:**

- **Pinecone metadata stays at the ADR-013 v1 schema.** Only `status` (and `organization_id`, future-proofing for cross-org guards) is actually filterable on. Listing-type, typology, location, price, structural facets all live on `property_listings` instead. Net: ~7 fewer fields per vector, no `update_metadata` consistency window to manage.
- **The `VectorIndex` port surface is unchanged** — no `or`, no `exists`. The filter sent to Pinecone is the simple AND of `status` + (optionally) `id.$in`. Adapters keep their existing operator set.
- **POI categories are not filterable** — same as before. They drive the soft signal via the embedded query's `NEARBY:` line (see §3) and the matched/unmatched bucket on the response (see §8).
- **The SQL pre-filter and the embedding call are independent** — `asyncio.gather` hides the SQL latency entirely on the happy path. Pinecone fires once the embed and the candidate list are both ready.

POI categories are **not** added as filters anywhere — the `pois` list on `property_listings` is a JSONB list of `{category, name, distance_meters, address, image_urls, reviews}`. Filtering JSONB containment on every search adds DB cost for negligible recall benefit (the POI signal is fundamentally soft — "perto de escola" is a preference, not a hard exclusion). POIs drive the soft signal via canonical text v3 (§3) and the per-result match/unmatch enrichment of the response payload (§8).

**Conflict resolution between route params and `ParsedQuery`:** the user's structured filters (FE form) take precedence over LLM-extracted ones for the same field, *except* when the route param is `None` and `ParsedQuery` has a value. Concrete rule: if a route param is set (e.g. `?typology=apartment`) and `ParsedQuery.typology` is also set (e.g. extracted "casa" from the query text), the route param wins. If the route param is None (e.g. the FE has no free-text price input), the `ParsedQuery` value applies. Rationale: form input is an explicit hard intent; extracted text is an inferred intent — and the user shouldn't have to fight their own form, but should benefit from the extractor when the form doesn't cover the dimension.

### 2a. NULL handling — native SQL `IS NULL OR …`

The structural fields on `property_listings` are *nullable* — agents may publish a listing without filling in `num_of_bedrooms`. A strict `gte` filter excludes those rows. We want them **included at the bottom of the result page** so the user still sees them — they might be the right match, the data is just missing — but listings that confirmed they satisfy the criterion rank above listings whose match status is unknown.

Because filtering happens in SQL, NULL handling is native and trivial. Each `ParsedQuery` clause is `(col IS NULL OR col >= value)`:

```sql
WHERE status = 'active'
  AND parish = $1                                  -- always-applied route filter
  AND (num_of_bedrooms IS NULL OR num_of_bedrooms >= $2)   -- soft-hard
  AND (has_pool IS NULL OR has_pool = true)
  AND (price_eur IS NULL OR price_eur <= $3)
  ...
LIMIT MAX_PRE_FILTER_CANDIDATES
```

No port-surface expansion, no `$or` / `$exists` translation in adapters, no metadata-schema bump — Postgres' query planner already handles this cleanly against the existing b-tree indexes on each filterable column.

**Application-side partition-and-rank** still happens after hydrate. The SQL pre-filter admits NULL-data rows into the candidate set; the use case sorts them to the bottom of the response page so they appear below confirmed matches:

- **Matched bucket** — every `ParsedQuery` criterion the row was tested against either passed (non-NULL and satisfies) or didn't apply (the criterion wasn't set). These rank by cosine, top first.
- **Partial-data bucket** — at least one `ParsedQuery` criterion couldn't be evaluated against the row because the underlying column was NULL. These rank by cosine *after* every matched row.

Pagination applies over the concatenation: matched rows first, partial-data rows second. `total = len(matched) + len(partial)` (mirroring ADR-013 v1's "Pinecone count survived ACTIVE hydrate" semantic, but driven by the SQL+intersection result instead).

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

The canonical-text bump (`v2` → `v3`) invalidates every cached `embedding_text_hash` — the existing hash-dedup mechanism (ADR-013 §3) treats hashes as `(text_version, text)` tuples. The vector-index metadata schema **does NOT bump** — it stays at ADR-013's V1 (`status`, `listing_id`, `organization_id`, …) and the structural facets stay where they always lived: on `property_listings`. That removes the consistency surface entirely; there's no `update_metadata` window during which Pinecone could disagree with SQL.

**Because the search isn't in production, there's no parallel-namespace dance.** The plan is:

1. Wipe the existing dev/staging vector namespace (nothing depends on it — search is gated off).
2. Bump `LISTING_CANONICAL_TEXT_VERSION` to `v3` in code. Same release as the SQL pre-filter + `QueryExtractor` wiring.
3. Run the existing `listings-canonical-text-backfill` spec mechanism: enqueue `PROPERTY_LISTING_UPDATED.v1` for every active listing. The handler re-renders v3, re-computes the hash, re-embeds, upserts into the (same) namespace. Metadata payload is unchanged from ADR-013 V1 — the handler doesn't need to touch `_index_metadata`.
4. Flip `LISTINGS_SEARCH_ENABLED=true` once the backfill drains and a manual query corpus passes.

If we go to production *with* the search dark, then later decide to bump the canonical text again, we'll need ADR-013's parallel-namespace pattern. For now, the system is malleable enough to refactor in place.

### 7. Latency budget

| Stage | ADR-013 budget | This ADR's budget |
|---|---|---|
| Query understanding (LLM) | 300ms p95 (free-text rewrite) | 400ms p95 (structured output adds ~100ms) |
| SQL pre-filter on `property_listings` | n/a | 30-50ms p95 (b-tree index lookups, parallel with embed) |
| EmbeddingProvider.embed | 150ms p95 | 150ms p95 (unchanged) |
| VectorIndex.query | 100ms p95 | 100ms p95 (smaller candidate set when ID filter applies, broader scan + post-intersection when it doesn't) |
| DB hydrate | 50ms p95 | 50ms p95 |
| **Total p95** | **600ms** | **700ms** |

Still under the 800ms end-to-end target. The structured-output penalty is small (gpt-4o-mini constrained generation against a Pydantic schema is fast — the model writes JSON it already knew the shape of), and the SQL pre-filter runs **in parallel with the embedding call** via `asyncio.gather`, so it doesn't add to the critical path on the happy path. The total grows by 100ms over ADR-013, all of it in the LLM layer.

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

- **This ADR** — `QueryExtractor` + SQL pre-filter on `property_listings` + `LISTING_CANONICAL_TEXT_V3` + matched/unmatched POI response.
- **Next (deferred)** — Cross-encoder re-ranker on top-50 → top-10 against the raw query (ADR-013 §6.7). Reach for this only when retrieval-quality data shows hybrid alone is insufficient.
- **Later (deferred)** — Personalization (saved searches, history feedback into ranking), multi-signal scoring (recency, popularity), faceted result counts ("X listings in Cascais, Y in Estoril, …").

## Consequences

**Positive:**
- Deterministic facets are evaluated deterministically at the database. A query mentioning "T3" pre-filters `WHERE typology='casa' AND (num_of_bedrooms IS NULL OR num_of_bedrooms >= 3) AND (has_pool IS NULL OR has_pool = true)` before the vector query runs. The Pinecone ANN then ranks the (much smaller) candidate set on the soft "perto de escola" signal. No more T2-with-a-great-description outranking a less-described T3.
- Single source of truth for structural filtering. The columns live on `property_listings`; we don't duplicate them onto every vector. Removes the consistency window (Pinecone metadata vs. SQL).
- `VectorIndex` port surface unchanged. No `or`/`exists` to add; existing in-memory + Pinecone + (future) turbopuffer/Qdrant/Weaviate adapters portable as-is.
- NULL semantics are SQL-native — one `IS NULL OR …` clause per soft-hard field, no orchestration cost.
- Sectional alignment between query and listing (via canonical text v3) should lift top-k quality without paying for a re-ranker.
- POI surface-form noise collapses onto a closed vocabulary.
- Structured extraction is unit-testable in a way text-rewriting never was. "T3" → `min_bedrooms=3` is a falsifiable assertion against worked examples.
- The route handler stays simple — the heavy lifting moves into a single replaceable use case (`SearchListings`, rewritten in place) behind a port.

**Negative:**
- Re-indexing every staged listing once (canonical-text v3 only). Free in dev; minor cost in staging. Mitigated by the backfill spec mechanism the canonical-text-backfill spec established.
- Adds an LLM call surface that must be reliable enough to extract correctly under load. Mitigated by the same fail-open envelope ADR-013 established — extractor errors degrade to "empty `ParsedQuery`, embed the raw query as DESCRIPTION:".
- One extra DB round-trip per search request (the SQL pre-filter). Mitigated by running it in parallel with the embedding call via `asyncio.gather` — net latency impact ~0 on the happy path.
- Widening `ListingPoi` from 3 fields to 6 grows the projection payload. Mitigated by the fact that the rich fields are already on the upstream snapshot (no new upstream work).
- The cardinality guard (§2) is a real piece of orchestration logic with two arms. Each arm needs test coverage; the "broad mode + intersect" path overshoots Pinecone's `top_k` by a configurable factor to survive intersection.

**Risks:**
- Over-extraction. The LLM might pull `has_pool=true` from a query mentioning a pool *negatively* ("não preciso de piscina"). Mitigated by prompt design ("treat negation conservatively — return null, not false") + a regression test on a negation corpus.
- Under-extraction. The LLM might miss "T3" and route the bedroom intent through cosine. Mitigated by extractor unit tests with worked examples; failures here degrade ranking but don't break correctness.
- Soft-hard filters can confuse users. A T2 with NULL `num_of_bedrooms` will appear (at the bottom) in a "T3" search — surprising if the user expected strict exclusion. Acceptable trade-off because the alternative (excluding NULL outright) is worse: missing-data listings would never surface in any structured search until an agent backfilled the column.
- The SQL pre-filter cardinality cliff at scale. If a popular area returns >`MAX_PRE_FILTER_CANDIDATES` matching IDs, the cardinality guard falls back to broad-mode (search whole namespace, intersect after). At very large catalog scales this could degrade — but at our v1 fanout (~thousands of listings) we expect candidate sets in the dozens-to-hundreds. Tunable via the constant.

## Sources

- ADR-013 (foundation): `docs/adr/013-listing-semantic-search.md`
- v1 read-path spec (shipped): `.claude/specs/archive/2026-05-listing-semantic-search-read-path.md`
- v1 indexing spec (shipped): `.claude/specs/archive/2026-05-listing-semantic-search.md`
- Implementation spec for this ADR: `.claude/specs/active/2026-05-listing-search-structured-extraction.md`
