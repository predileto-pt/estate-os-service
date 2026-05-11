# ADR-014: Listing semantic search v2 — structured query extraction + hybrid retrieval

**Date:** 2026-05-11
**Status:** Draft
**Relates to:** Extends ADR-013 (which shipped phase 1 indexing + phase 2 read path). Does not supersede — adds a new query-understanding contract (`QueryExtractor` returning a typed `ParsedQuery`), a new vector-index metadata schema (`LISTING_INDEX_METADATA_V2`), and a new canonical-text version (`LISTING_CANONICAL_TEXT_V3`). The v1 read path stays callable behind a separate gate during rollout.

## Context

ADR-013 phase 2 shipped a read path that runs `QueryUnderstandingService.rewrite` (free-text → free-text PT canonicalization) → `EmbeddingProvider.embed` → `VectorIndex.query` with status + location + listing_type + typology + price as hard filters → DB hydrate. The pipeline works, but the architecture leaves three signals on the table:

1. **Deterministic facets are evaluated as soft signals.** The query *"casa T3 com piscina"* names three structured intents: `typology=casa`, `min_bedrooms=3`, `has_pool=true`. ADR-013 v1 hard-filters typology (when present as a route param) but routes the bedroom-count and pool intents through cosine. Cosine doesn't distinguish "the listing mentions piscina because it has one" from "the listing mentions piscina because the agent's blurb compared it favourably to a neighbour's." Hard filters do. The structural fields are already on `property_listings` (`num_of_bedrooms`, `has_pool`, `has_garden`, `has_elevator`, `area_in_m2`, `parking_spaces`) — we just don't expose them to the query side.

2. **Query side and listing side don't share an explicit structure.** The canonical-text composer renders the listing as `TYPOLOGY: ... NEARBY: ... FEATURES: ...` (`LISTING_CANONICAL_TEXT_V2`). The v1 query rewriter emits **free text** ("casa com varanda, perto de ginásio"). Cosine has to do the alignment implicitly. Aligning the two sides — both speak the same sectional vocabulary — should improve top-k quality without paying for a cross-encoder.

3. **POI categories carry surface-form noise.** A query mentioning "academia" should hit listings tagged with `gym` POIs. ADR-013 v1 leans on the LLM rewriter to normalize ("academia" → "ginásio") and on the multilingual embedder to bridge any remaining gap. Collapsing both query- and listing-side onto a **closed POI category vocabulary** (the same enum the property POI workflow uses) removes the failure mode entirely.

These are observations from the architecture, not from traffic. v1 hasn't seen production load yet. ADR-014 is therefore a design-from-first-principles exercise informed by ADR-013's deferred items. The cross-encoder re-ranker that ADR-013 §6.7 / v6 sketched stays deferred — re-ranking is a quality-of-top-10 tool, and we shouldn't reach for it before exhausting the cheaper structural improvements below.

## Decision

### 1. Query understanding becomes structured extraction

Replace `QueryUnderstandingService.rewrite(query: str) -> str` with `QueryExtractor.extract(query: str) -> ParsedQuery`. `ParsedQuery` is a typed value object:

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

### 2. Hybrid retrieval — hard filters for deterministic facets, soft signal for the rest

The vector query filter becomes the AND of three blocks:

```
filter = AND(
    # ADR-013 phase 2 filters (preserved as-is)
    status = "active",
    location filter (parish/municipality/district from the FE selector),
    structured filters from the route params (listing_type, typology, price),

    # NEW: ParsedQuery hard filters (only emitted when the field is non-None)
    typology = parsed.typology               // overrides the route param if set
    num_of_bedrooms >= parsed.min_bedrooms
    num_of_bathrooms >= parsed.min_bathrooms
    area_in_m2 >= parsed.min_area_m2
    area_in_m2 <= parsed.max_area_m2
    price_eur >= parsed.min_price
    price_eur <= parsed.max_price
    has_pool = true        // when parsed.has_pool is True
    has_garden = true      // when parsed.has_garden is True
    has_elevator = true    // when parsed.has_elevator is True
    has_parking = true     // when parsed.has_parking is True
)
```

POI categories are **not** added as metadata filters — the `pois` list on `property_listings` is a JSONB list of `{category, name, distance_meters}`, and turning that into N booleans on the vector metadata explodes the metadata size and the per-category cardinality. Instead, **POIs become a soft signal in the embedded query text** (see §3 — canonical text v3 NEARBY: line).

**Conflict resolution between route params and `ParsedQuery`:** the user's structured filters (FE form) take precedence over LLM-extracted ones for the same field. Concrete rule: if a route param is set (e.g. `?typology=apartment`) and `ParsedQuery.typology` is also set (e.g. extracted "casa" from the query text), the route param wins. The extracted value is logged at INFO for observability but ignored at the filter layer. Rationale: form input is an explicit hard intent; extracted text is an inferred intent — and the user shouldn't have to fight their own form.

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

POI categories are pulled from a closed enum living in the properties context (shared via the snapshot the listings projector consumes). The full list is owned by `properties` (the POI auto-discovery workflow defines it); listings imports it as a re-export from the carried-state event payload. The closed-vocabulary commitment is the architectural decision — the specific enum members are an implementation detail tracked in the v2 spec.

Surface-form normalization happens **at extraction time** (the LLM is prompted with the closed enum and asked to map surface forms onto it: "academia" → `gym`, "primária" → `school`, "talho" → `food_shop`). This collapses synonym mismatches that v1 relied on the embedder to bridge.

### 6. Re-indexing strategy

The canonical-text bump (`v2` → `v3`) invalidates every cached `embedding_text_hash` — the existing hash-dedup mechanism (ADR-013 §3) treats hashes as `(text_version, text)` tuples. The metadata schema bump (`V1` → `V2`) invalidates every indexed metadata payload — Pinecone's `update_metadata` would patch in place, but a fresh re-upsert is simpler and the embedding handler's hash mismatch will trigger it anyway.

**Parallel-namespace rollout** (same pattern as ADR-013's "Bumping the embedding model"):

1. Provision a new namespace string (`openai-text-embedding-3-small-v2`). The model doesn't change; only the canonical-text/metadata schemas do — so the namespace name encodes the schema version, not the model.
2. Backfill via the existing `listings-canonical-text-backfill` spec mechanism: enqueue `PROPERTY_LISTING_UPDATED.v1` for every active listing. The handler re-renders canonical text v3, re-computes the hash, re-embeds, re-upserts into the new namespace.
3. Validate against a query corpus offline.
4. Atomically flip `VECTOR_INDEX_NAMESPACE` (and `LISTINGS_SEARCH_ENABLED_V2`).
5. Drop the v1 namespace.

The v1 read path stays callable through step 4 — the `SearchListings` v1 use case can stay wired against the v1 namespace until the flag is flipped. v1 and v2 don't share a code path; they share an outer route handler.

### 7. Latency budget

| Stage | v1 budget | v2 budget |
|---|---|---|
| Query understanding (LLM) | 300ms p95 | 400ms p95 (structured output adds ~100ms) |
| EmbeddingProvider.embed | 150ms p95 | 150ms p95 (unchanged) |
| VectorIndex.query | 100ms p95 | 100ms p95 (richer filter but Pinecone's metadata filter is O(1) per clause) |
| DB hydrate | 50ms p95 | 50ms p95 |
| **Total p95** | **600ms** | **700ms** |

Still under the 800ms end-to-end target. The structured-output penalty is small because `gpt-4o-mini` constrained generation against a Pydantic schema is fast — the model writes JSON it already knew the shape of.

### 8. Backwards compatibility and feature gating

- `LISTINGS_SEARCH_ENABLED_V2` (new) — when `true`, the v2 pipeline runs. When `false`, the route falls back to v1 (`SearchListings` from ADR-013 phase 2).
- The route layer branches on `getattr(container, "search_listings_v2", None)` exactly the way it currently branches on `search_listings`. Same defensive pattern.
- The legacy `LISTINGS_SEARCH_ENABLED` (v1 gate) stays around for one release cycle so we can roll back the read path while v2 is bedding in.

### 9. Iteration plan

- **v2 (this ADR)** — `QueryExtractor` + `LISTING_INDEX_METADATA_V2` + `LISTING_CANONICAL_TEXT_V3` + hybrid retrieval.
- **v3 (deferred)** — Cross-encoder re-ranker on top-50 → top-10 against the raw query (ADR-013 §6.7). Reach for this only when retrieval-quality data shows hybrid alone is insufficient.
- **v4 (deferred)** — Personalization (saved searches, history feedback into ranking) and multi-signal scoring (recency, popularity).
- **v5 (deferred)** — Faceted result counts ("X listings in Cascais, Y in Estoril, …").

## Consequences

**Positive:**
- Deterministic facets are evaluated deterministically. A query mentioning "T3" excludes T1s instead of down-ranking them. Concretely: if a user says "casa T3 com piscina perto de escola", the result set is `WHERE typology='casa' AND num_of_bedrooms >= 3 AND has_pool = true`, then ANN-ranked by the soft "perto de escola" signal. No more T2-with-a-great-description outranking a less-described T3.
- Sectional alignment between query and listing should lift top-k quality without paying for a re-ranker.
- POI surface-form noise collapses onto a closed vocabulary.
- Structured extraction is unit-testable in a way text-rewriting never was. "T3" → `min_bedrooms=3` is a falsifiable assertion against worked examples.
- The route handler stays simple — the heavy lifting moves into a single replaceable use case (`SearchListingsV2`) behind a port.

**Negative:**
- Re-indexing every published listing once. Cost = (active listing count) × (one embed call + one upsert). Mitigated by the backfill spec mechanism the canonical-text-backfill spec established.
- Adds an LLM call surface that must be reliable enough to extract correctly under load. Mitigated by the same fail-open envelope as v1 — extractor errors degrade to "empty `ParsedQuery`, embed the raw query as DESCRIPTION:".
- The vector metadata size grows by ~7 fields per vector. Still well under Pinecone's 40KB cap.
- A schema version bump (canonical text v2→v3, metadata V1→V2) is a coordinated rollout. ADR-013 already lays out the parallel-namespace pattern; we just exercise it.

**Risks:**
- Over-extraction. The LLM might pull `has_pool=true` from a query mentioning a pool *negatively* ("não preciso de piscina"). Mitigated by prompt design + a regression test on a negation corpus.
- Under-extraction. The LLM might miss "T3" and route the bedroom intent through cosine. Mitigated by extractor unit tests with worked examples; failures are quality issues, not correctness bugs.
- Hard filters can over-narrow. If the user says "T3" and we hard-filter `num_of_bedrooms >= 3`, we exclude listings missing the `num_of_bedrooms` column entirely (NULL). Treat NULL as "unknown, include in soft set" — i.e. the filter becomes `num_of_bedrooms IS NULL OR num_of_bedrooms >= 3`. This is a Pinecone filter quirk worth pinning in the implementation spec.

## Sources

- ADR-013 (foundation): `docs/adr/013-listing-semantic-search.md`
- v1 read-path spec (shipped): `.claude/specs/archive/2026-05-listing-semantic-search-read-path.md`
- v1 indexing spec (shipped): `.claude/specs/archive/2026-05-listing-semantic-search.md`
- Implementation spec for this ADR (to be drafted): `.claude/specs/active/2026-05-listing-search-v2-structured-extraction.md`
