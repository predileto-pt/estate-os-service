# ADR-010: Property listing enrichment — POIs, cost-of-living, and semantic search

**Date:** 2026-05-06
**Last updated:** 2026-05-08 (v7 — failure modes, retry policy, freshness; ADR accepted)
**Status:** Accepted

## Context

Properties get a `property_listings` row from creation onward (initially with `status=DRAFT`), and become visible on the public portal when published — visibility is enforced by the public route's `WHERE status = ACTIVE` filter. Today we project that row with address fields enriched (parish / municipality / district via the address-enrichment handler). That's enough to make a published listing appear on the portal — it's not enough to power the search experiences product wants next:

- "Show me houses near good schools, a pharmacy, and a supermarket."
- "Show me listings where a family of four would spend under €1,800/month on groceries, transport, school transfers, and personal expenses combined."
- "I'm looking for a quiet area with a gym and a coffee shop within walking distance" — answered semantically, not by string-matching the description (addressed by stage 4 of the workflow, deferred per v4 §1; the port surface lands in v4 §3.5 so the deferral is structural-cost-free).

Three observations make this a separate ADR rather than a one-paragraph extension to the projector:

1. **The work is heavy.** A POI lookup is one Google Places API call per category × radius — paid per call, slow (hundreds of ms each), and rate-limited. Doing it inside the projector's hot path would couple every property publish to a multi-second external pipeline.
2. **The signal is computed, not extracted.** A "cost-of-living score for this listing assuming a family of N adults + M children" is derived from POI density, distances, and configurable per-person cost coefficients. It's product policy, not domain truth — it has to be re-derivable as the formula evolves.
3. **It overlaps with existing amenity discovery — but is not the same thing.** The properties context already has `DiscoverPropertyAmenities` (`src/properties/application/use_cases/discover_property_amenities.py`) writing into `PropertyAmenity` (`src/properties/domain/models/property_amenity.py`) with categories `HOSPITAL`, `BANK`, `GROCERY`, `SCHOOL`, … That feature is **agent-facing** (an agent triggers it from the dashboard to enrich a single property they manage). What this ADR proposes is **search-facing** (the system runs it automatically on every newly-published listing so the public read API can rank by cost-of-living and answer semantic queries). Same data sources, different consumers, different lifecycles.

## Decision

When the listings projector inserts a brand-new `property_listings` row (i.e. `applied=true` and the row didn't previously exist), it emits a new domain event `PROPERTY_LISTING_CREATED.v1`. A new listings-context handler consumes it and runs a multi-stage enrichment workflow that produces three artifacts on the `property_listings` row:

1. **POI catalog** — nearby places per category (schools, banks, pharmacies, groceries, hospitals, transit stops, …) with distances.
2. **Cost-of-living score** — a structured estimate of monthly living cost for one or more household compositions, derived from the POI catalog + configurable cost coefficients.
3. **Semantic embedding** — a vector representation of the listing's "lifestyle profile" (description + POI summary + location features) for vector-similarity search.

### 1. New domain event: `PROPERTY_LISTING_CREATED.v1`

Distinct from `PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT.v1` (which fires on every applied upsert and only re-resolves parish / municipality / district):

- `PROPERTY_LISTING_CREATED.v1` fires **once** per listing, when the row is first inserted into `property_listings`. Updates do not re-fire it; they fire `PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT.v1` instead.
- Carries the same payload shape as `build_property_snapshot()` plus the resolved location fields (address, parish, municipality, district, lat, lon).
- Subscribed by a new listings-context handler (single subscriber for now; the topic exists so other contexts can subscribe later — analytics, search index warming, etc. — without reaching into listings internals).

The projector already distinguishes insert from update implicitly via the `ON CONFLICT … WHERE source_aggregate_version < excluded.source_aggregate_version` predicate. Detecting "first insert" precisely will require either:

- A second SELECT before the upsert to check for prior existence, OR
- A `RETURNING (xmax = 0)` trick on the upsert to know whether it was an INSERT or UPDATE.

The second is preferred — one round-trip, no race window. Detail to be locked in during the implementation spec.

### 2. New workflow: POI discovery + cost-of-living scoring

A new handler `handle_property_listing_created` in `src/listings/adapters/workers/` consumes `PROPERTY_LISTING_CREATED.v1` and:

1. **Fetches nearby places** for a fixed category set (initial: schools, banks, pharmacies, groceries, hospitals, public transit) within a configurable radius (default ~1.5 km), via a `PoiProvider` port (Google Places adapter to start; OpenStreetMap / Overpass adapter is an alternative we deliberately punt on).
2. **Computes a cost-of-living score** from the POI catalog + a `CostModel` configurable via env vars:
   - `COST_PER_ADULT_EUR_MONTH` — base monthly personal expenses per adult.
   - `COST_PER_CHILD_EUR_MONTH` — base monthly personal expenses per child.
   - `COST_PROXIMITY_WEIGHTS` — per-category multipliers that adjust the base cost up or down based on distance to the nearest POI in that category (e.g. nearest grocery >1 km adds a transport-cost surcharge; nearest school >2 km adds a school-transfer surcharge).
   - The exact formula is intentionally undefined in this ADR — it's product policy that will be tuned. The ADR commits only to: cost is a deterministic, recomputable function of `(poi_catalog, cost_model)` and is stored on the row alongside the model version.
3. **Computes a semantic embedding** from the listing's text fields plus a synthetic POI summary string ("near 3 schools, a pharmacy, a supermarket, a transit stop within 800m"). The embedding goes into a vector column on `property_listings` (pgvector, since Supabase already speaks it) for cosine-similarity search.
4. **Persists** the POI catalog (probably a child table `property_listing_pois`), the cost score (column on `property_listings`), the cost-model version (column), and the embedding (vector column).

### 3. Configuration (env vars)

```bash
# Cost-of-living model — version this every time the formula changes so
# rows can be re-scored selectively.
COST_MODEL_VERSION=v1
COST_PER_ADULT_EUR_MONTH=900
COST_PER_CHILD_EUR_MONTH=400

# POI provider
POI_PROVIDER=google_places          # google_places | osm
POI_RADIUS_METERS=1500
GOOGLE_MAPS_API_KEY=...              # already configured for amenity discovery

# Embeddings
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536
```

Detail to lock in during follow-up specs: per-category cost weights (`COST_PROXIMITY_WEIGHTS`) — likely a JSON env var or a config file.

### 4. Search-time use

Public listing search (`GET /api/v1/listings/properties`) gains optional query parameters:

- `household=2A2C` (or similar shorthand for "2 adults, 2 children") — filters/ranks results by predicted monthly cost-of-living.
- `max_monthly_cost=1800` — hard filter.
- `q="quiet apartment near good schools"` — semantic query, computed against the stored embeddings via cosine similarity.

The exact API surface is a separate spec under `listings-cursor-pagination-and-filters` — this ADR commits to "the storage and signals exist," not to the route shape.

### 5. Failure semantics

POI fetch and embedding generation are external calls — they fail. The handler runs them sequentially; on failure of any stage:

- Persistence of completed stages is **best-effort**: we save what we have and re-raise so SQS redelivers (per ADR-008 per-handler DLQ).
- Listings remain visible on the portal with NULL POI / cost / embedding columns until enrichment lands. A row never blocks the portal because its enrichment is still pending.
- A monitor query on `property_listings WHERE poi_catalog IS NULL AND created_at < now() - interval '1 hour'` flags stuck enrichments.

## Consequences

- **New SNS topic** `domain-events-PROPERTY_LISTING_CREATED-v1` (and the matching subscription on `listings-events-queue`). Adds one entry to `scripts/localstack-init.sh` and one to the production SNS provisioning.
- **`property_listings` schema grows.** New columns: `poi_catalog jsonb`, `cost_score jsonb`, `cost_model_version text`, `embedding vector(1536)`, `enriched_at timestamptz`, `enrichment_attempts int`. Migration in alembic.
- **A new child table `property_listing_pois`** if we decide to model POIs relationally instead of jsonb. Locked in during the implementation spec.
- **Two new ports** in `src/listings/application/ports/`: `PoiProvider`, `EmbeddingProvider`. Two new adapters: Google Places + OpenAI embeddings.
- **Cost-model versioning is mandatory.** Every stored cost score carries the `cost_model_version` it was computed under. When the formula changes, a backfill job re-scores rows whose version is stale — never an in-place silent drift.
- **Read-side schema is now load-bearing for the search experience.** Any future change to `property_listings` shape touches both the projector and the enrichment handler; tests have to cover both projection paths.
- **One paid external dependency adds load per published listing.** Google Places quota and cost become operational concerns; rate-limiting and caching strategy belong in the implementation spec, not here.

## Alternatives considered

1. **Compute cost-of-living at read time, not at projection time.** Rejected: the POI lookup is the slow part, not the math. Pre-computing once per listing keeps the search endpoint fast and lets us evolve the formula without re-fetching POIs.
2. **Reuse `PropertyAmenity` from the properties context.** ~~Rejected~~ **Reversed in v2 (see below).** Initially rejected on the grounds that the agent-triggered flow shouldn't drive search-side data. v2 inverts this: the discovery use case is shared infrastructure invoked by both triggers (agent button + listing-created event), and the agent path simply becomes one of two callers. Search results no longer depend on whether an agent clicked anything — the event-driven path runs automatically on every publish.
3. **Trigger enrichment on every `PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT.v1` event.** Rejected: address re-enrichment fires on every property update; POI / cost / embedding work is expensive and shouldn't run when only a price changed. Splitting the event types lets each handler scale and DLQ independently.
4. **Single combined event `PROPERTY_LISTING_NEEDS_ENRICHMENT.v1` with a "stage" field.** Rejected: violates the one-event-one-meaning convention from ADR-008. Topic-per-meaning is what gives us per-handler isolation.
5. **External vector database (Pinecone, Weaviate, Qdrant).** Punted to a follow-up. pgvector inside Supabase is the simplest first move; we can extract later if scale demands it. Whatever we pick, the `EmbeddingProvider` port stays.

## Out of scope

- **Exact cost formula and per-category weights** — product policy, defined in the implementation spec.
- **Public API surface for cost / semantic search filters** — defined in (or alongside) `listings-cursor-pagination-and-filters`.
- **Backfill strategy** for existing `property_listings` rows that predate this ADR — separate spec; likely a one-shot CLI under `src/listings/entrypoints/backfill_property_listings.py` (which already exists for the projection backfill).
- **Re-scoring on cost-model version bump** — separate spec; the column-versioning scheme above is the foundation.
- **POI freshness** (re-fetch when POIs change in the world) — separate spec; out-of-scope for v1.
- **Multilingual embeddings** — descriptions in this codebase are PT today; embedding model choice may need to revisit when we expand.

## v2 — Reuse existing amenity discovery, expand the category list

The properties context already ships a working amenity discovery pipeline that's well-engineered and exactly the building block we need:

- **`PlacesService` port** at `src/properties/application/ports/places_service.py` — clean abstraction over Google Places (`find_nearby(lat, lon, place_type, radius_meters, keyword)` returns `list[NearbyPlace]`).
- **Google + in-memory adapters** at `src/properties/adapters/places/google_places_service.py` and `…/inmemory/inmemory_places_service.py`.
- **`AmenityCategory` enum + `CATEGORY_PLACE_TYPE_MAP`** in `src/properties/domain/models/property_amenity.py` and `discover_property_amenities.py:35` — maps domain categories to Google Place type strings.
- **`DiscoverPropertyAmenities` use case** at `src/properties/application/use_cases/discover_property_amenities.py` — concurrent fan-out (5 parallel calls via `gather_with_concurrency`), ranking via `amenity_ranker`, persists `PropertyAmenity` rows.
- **`amenity_ranker` domain service** — proximity-weighted ranking, `TOP_PLACES_LIMIT = 5` per category.

v1's "build a parallel system in listings" position is reversed. v2 commits to **one canonical amenity-discovery pipeline, two triggers**:

### Architectural pattern: callable Protocol port (matches CLAUDE.md cross-context rules)

Per the project convention (CLAUDE.md §"Cross-context dependency rules"), the listings context does not import properties' domain classes. Instead, properties exposes a callable Protocol that listings consumes via constructor injection — same pattern as `RegisterUserPort` (identity → organizations) and `SeedFreemiumSubscription` (billing → organizations).

```python
# src/properties/application/ports/discover_amenities_for_property.py
class DiscoverAmenitiesForPropertyPort(Protocol):
    async def __call__(self, *, property_id: UUID) -> list[PropertyAmenityDTO]: ...
```

- Properties wires `DiscoverPropertyAmenities` as the implementation.
- Listings receives the port at container construction (`get_listing_container()` injects it).
- The new `handle_property_listing_created` handler invokes the port and reads back the amenities for cost-scoring + embedding.

The agent-button flow is unchanged — it still calls `DiscoverPropertyAmenities` directly. The new event-driven flow goes through the port. **Same use case, two callers.**

### Single source of truth for POI data: `PropertyAmenity`

The properties context owns the canonical POI store (`property_amenities` table). The listings handler does **not** duplicate POI rows into a `property_listings.poi_catalog` jsonb column. Instead:

- Listings reads amenities by `property_id` via a second port (`GetAmenitiesForProperty`) for cost-scoring + embedding-summary purposes.
- `property_listings` gains the **derived** columns from v1 (`cost_score`, `cost_model_version`, `embedding`, `enriched_at`, `enrichment_attempts`) but no `poi_catalog` of its own.
- The amenity catalog is read-side data that already has a home; we don't shadow it.

This collapses one of v1's planned columns and one potential child table. Net schema delta on `property_listings` is smaller.

### Expanded category list

`AmenityCategory` today (`src/properties/domain/models/property_amenity.py:9`): `HOSPITAL`, `BANK`, `GROCERY`, `SCHOOL`, `LAUNDRY`, `COFFEE_SHOP`, `PHARMACY`, `GYM`, `RESTAURANT` — 9 categories.

For "everything necessary for humans" + cost-of-living relevance, the v2 category set adds:

| New category     | Google Place type(s)                                                                            | Why                                                                                                            |
| ---------------- | ----------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `GAS_STATION`    | `gas_station`                                                                                   | Private-transport cost driver (explicit user request)                                                          |
| `PUBLIC_TRANSIT` | `bus_station`, `subway_station`, `train_station`, `transit_station` (compose into one category) | The single biggest cost-of-living lever — proximity flips the household budget from "needs a car" to "doesn't" |
| `KINDERGARTEN`   | `primary_school` (use keyword "creche"/"infantário" for PT)                                     | Child-care cost; high signal for families                                                                      |
| `PARK`           | `park`                                                                                          | Lifestyle / quality-of-life signal for semantic search                                                         |
| `POST_OFFICE`    | `post_office`                                                                                   | Utility access                                                                                                 |
| `LIBRARY`        | `library`                                                                                       | Lifestyle / education-adjacent                                                                                 |
| `SHOPPING_MALL`  | `shopping_mall`                                                                                 | Discretionary-spend access                                                                                     |
| `BAKERY`         | `bakery`                                                                                        | High frequency in PT urban living                                                                              |
| `POLICE_STATION` | `police`                                                                                        | Safety perception (drives semantic results, not cost)                                                          |

That brings us to **18 categories**. Each one is a Google Places call per listing — at 5-way concurrency the existing adapter already handles, total wall time is roughly ceil(18/5) × per-call latency ≈ 4 sequential rounds. Acceptable for an async background handler.

The `CATEGORY_PLACE_TYPE_MAP` becomes a `dict[AmenityCategory, list[str]]` to support multi-type categories like `PUBLIC_TRANSIT`. The use case fans out one call per `(category, type)` pair and merges results before ranking.

### Improvements to the existing discovery use case

Reusing isn't free — three tightenings to land alongside the new categories:

1. **Multi-type categories.** `CATEGORY_PLACE_TYPE_MAP` widens to `list[str]`; the call layer flattens. `PUBLIC_TRANSIT` is the motivating case (covers buses, metro, train).
2. **Make discovery idempotent.** Today `delete_by_property_id` + `save_batch` runs every invocation (`discover_property_amenities.py:112-114`). For event-driven runs we want it to skip when fresh data exists (e.g. a `discovered_at < now() - interval '30 days'` guard), to avoid spending Google quota on every retry. Add a `force=False` parameter that the agent-button flow passes as `True` (explicit refresh) and the event-driven flow passes as `False` (skip if recent).
3. **Persist a `place_type` field on `PropertyAmenity`.** Currently we store the category bucket but not the underlying Google type. For multi-type categories like `PUBLIC_TRANSIT` we lose the "is this a bus stop or a subway?" detail. Add the column; backfill is trivial since old rows have a 1:1 category→type map.

### Updated cross-context wiring

```
                      ┌─ properties.DiscoverPropertyAmenities ─┐
                      │                                         │
agent button ─────────┘                                         ├── PlacesService (Google)
                                                                │
listings.handle_property_listing_created ──► DiscoverAmenities  │
                          │                  ForPropertyPort ───┘
                          │                  (callable Protocol)
                          ▼
                  cost_score + embedding
                  on property_listings
```

Listings depends on properties via two callable Protocols:

- `DiscoverAmenitiesForPropertyPort` — kicks off discovery if needed.
- `GetAmenitiesForPropertyPort` — reads the result for cost-scoring.

No domain class crosses the boundary; both ports are plain dataclasses (DTOs) at the wire.

### Consequences amended

- v1's planned `poi_catalog jsonb` column on `property_listings` is **dropped** — the canonical store remains `property_amenities` in properties.
- `AmenityCategory` enum gains 9 new variants. Migration: alembic `op.execute("ALTER TYPE ...")` to add enum values, plus a code-level constant update.
- `property_amenities` schema gains a `place_type text` column (and the index it deserves).
- `DiscoverPropertyAmenities` gains a `force: bool` parameter and a freshness check.
- One more port file in properties (the `DiscoverAmenitiesForPropertyPort` protocol).
- Listings container gets two new constructor params (the two callable Protocols above).

The cost score / embedding / model versioning from v1 §1-§5 stays as-is. The only structural change is **where POI data lives** (it stays in properties, not duplicated to listings).

## v3 — Command-driven trigger, configurable settings, manual editability

v1 wired enrichment to a new `PROPERTY_LISTING_CREATED.v1` event auto-fired by the projector. v3 reverses that and pivots to a **command-driven** model that matches the existing agent-button pattern, then layers in manual editability and runtime-tunable provider selection.

### 1. Drop the event, use a command

The pivot reasoning, in three points:

- **Cost is bounded by intent.** Auto-on-publish burns API quota on every published listing, even ones nobody will search. Manual click means the agent decides which listings deserve enrichment.
- **The pattern already exists.** `POST /api/v1/admin/property-amenities/discover` (`src/properties/adapters/api/routes/property_amenities.py:70-107`) returns 202 and dispatches to a worker today. We're not inventing — we're extending what's shipped, with cleaner names.
- **The existing endpoint has a smell to fix.** It publishes `DomainEvent(event_type=PROPERTY_CREATED_V1, …)` to manually re-trigger discovery. That conflates two concepts: domain events (state-of-the-world facts, fan-out, past-tense) and commands (do-this-now intents, point-to-point, imperative). Per ADR-008, commands belong on dedicated SQS queues via `SQSCommandPublisher`, not on the SNS-fanned event bus. v3 fixes this distinction in the new flow.

**Ownership recap (corrected from v3 first draft):**

POIs are facts about a Property's location — same shelf as lat/lon, address, characteristics. They exist for DRAFT properties (agent preview before publish) and don't change when a property is published. The Listing is a _projection_ of the Property — it should derive from Property data, not own its own copy of facts that already exist upstream.

Therefore:

- **Properties owns POIs** — the raw discovered amenities, the agent-button discovery, the `manually_edited` flag, the per-row edit endpoints. `PropertyAmenity` stays where it is.
- **Listings owns derived signals** — `cost_score`, `cost_model_version`, `embedding`. These are functions of `(POIs, cost_model)` and `(description, POI summary)` and are _search-side_ signals, not facts about the property.
- **The trigger lives on properties.** The workflow originates from a Property aggregate; the listings-side derived signals are computed as the workflow's last two stages.

**v3 design:**

- New admin endpoint: `POST /api/v1/admin/properties/{property_id}/enrich?organization_id=<uuid>`. Returns 202. Gates on `require_org_member`. Optional body `{"force": bool}` (default `false` — skip if recently enriched).
- New bulk endpoint: `POST /api/v1/admin/properties/enrich-batch?organization_id=<uuid>` with body `{"status": "active"}` (default — only enrich published properties; can broaden to `"all"` if product wants). Enqueues one `ENRICH_PROPERTY_REQUESTED.v1` per matching property. Agencies bulk-enrich on opt-in. **The agent owns the cost; we don't auto-spend.**
- New command type: `ENRICH_PROPERTY_REQUESTED.v1` carrying `{property_id, organization_id, force, stages?: ["pois", "cost", "embedding"], requested_by_user_id}`. Default `stages` is all three. Manual edits trigger an `["embedding"]`-only re-run (see §3).
- New SQS queue: `property-enrichment-queue` + `property-enrichment-dlq` with `maxReceiveCount=5` (matches every other command queue per ADR-008).
- New worker entrypoint: `properties.entrypoints.enrichment_worker --queue enrichment`. Consumes the command, runs the three stages from v1 §2 reusing the existing `DiscoverPropertyAmenities` use case for stage 1. Stages 2 and 3 (cost score, embedding) write to `property_listings` via a `ListingDerivedSignalsRepository` port — listings exposes that port; properties' worker consumes it. Cross-context write through a Protocol port, not direct table access.
- The existing `POST /api/v1/admin/property-amenities/discover` endpoint (`src/properties/adapters/api/routes/property_amenities.py:70-107`) is **deprecated and removed in this work**. Its behavior — agent-button-triggered amenity discovery — is folded into `/properties/{id}/enrich` with `{stages: ["pois"]}` for the discover-only case. Cleaning up the smell from §1 (domain-event-as-command).

**Dropped from v1:**

- `PROPERTY_LISTING_CREATED.v1` domain event — gone. Not needed.
- The `RETURNING (xmax = 0)` insert-vs-update detection trick in the projector — gone. Projector's job stays "upsert + queue address re-enrichment," nothing more.
- Auto-trigger from any event handler — gone, but see promotion path below.

### 2. Use case + service shape

The work splits across both contexts: properties owns the orchestrator (because the trigger lives on a Property), listings owns the derived-signals write surface and its edits.

```
# Properties context — workflow trigger + amenity edits
src/properties/application/use_cases/
├── enrich_property.py                    # orchestrator — consumed by the worker
├── update_property_amenity.py            # manual edit (single amenity row)
└── replace_property_amenities.py         # manual edit (replace whole catalog for a category)
src/properties/application/services/
└── (uses existing amenity_ranker)

# Listings context — derived signals + their edit surface
src/listings/application/use_cases/
└── update_listing_cost_score.py          # manual override of cost-score numbers
src/listings/application/services/
├── cost_scoring_service.py               # stage 2 — pure function over (pois, cost_model)
└── embedding_service.py                  # stage 3 — calls EmbeddingProvider
src/listings/application/ports/
└── listing_derived_signals_repository.py # write port — properties' worker writes through this
```

**Why use cases at the orchestrator + edit layer, services in the middle:** the orchestrator and edits are entry points (worker / HTTP route) — they're "use cases" in the hexagonal sense. The stages are reusable computations the orchestrator composes; "service" is the right label per the existing `src/properties/domain/services/amenity_ranker.py` precedent.

**Cross-context write path:** `EnrichProperty` (properties' worker) calls the existing `DiscoverPropertyAmenities` for stage 1, then invokes `ListingDerivedSignalsRepository.upsert(property_id, cost_score, embedding, …)` — a port owned by listings, implemented by listings' SQLAlchemy adapter, injected into the properties container at construction. This is the same callable-Protocol pattern from CLAUDE.md (`RegisterUserPort`, `SeedFreemiumSubscription`). No domain class crosses the boundary; the port surface is plain DTOs.

Naming note: the user-suggested `EnrichmentEvaluation` was considered. Rejected because "evaluation" implies scoring/judgment, which only fits stage 2 — not POI discovery or embedding. `EnrichProperty` is imperative, matches the existing verb-pattern of `PublishProperty` / `UpdatePropertyOwnerContact`, and reads cleanly as the worker's `await use_case.execute(…)` call site.

### 3. Manual editability — new requirement

Every value the enrichment process produces must be editable by the agent afterward. Discovery is best-effort; the agent has ground truth we don't. Edits land where the data lives — POI edits on the properties admin surface (extending the existing `property-amenities` collection), cost-score edits on the listings admin surface.

**What's editable:**

| Artifact                                         | Where it lives | Edit endpoint                                                         | Edit semantics                                                                                                                                                                                          |
| ------------------------------------------------ | -------------- | --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Individual amenity (name, distance, place_type)  | properties     | `PATCH /api/v1/admin/property-amenities/{amenity_id}`                 | Update one row. Sets `manually_edited=true`. Extends the existing `property-amenities` resource.                                                                                                        |
| Amenity catalog for one category on one property | properties     | `PUT /api/v1/admin/properties/{property_id}/amenities?category=<cat>` | Body is the new amenity list for that category. Marks all rows `manually_edited=true`. The property-anchored sub-resource matches `/{property_id}/address` and `/{property_id}/publish`.                |
| Cost score override                              | listings       | `PATCH /api/v1/admin/listings/properties/{property_id}`               | Body has `cost_score`. Sets `cost_score_manually_edited=true`. Sub-resource of the admin listings collection (`/api/v1/admin/listings/properties` already exists from the just-shipped admin endpoint). |
| Embedding                                        | listings       | — not directly editable                                               | Derived; auto-recomputes after any amenity / description / cost-score edit (see below).                                                                                                                 |

**URL design rationale:**

- **Single-row amenity edits** stay on the existing `property-amenities` collection — kebab-case sibling resource, matches `property-owners`, `property-prices`, `property-images`. Agents already know this URL.
- **Bulk replace by category** moves to the property-anchored sub-resource path (`/properties/{id}/amenities?category=…`) instead of a query-param POST on the collection. This is the same shape as `/properties/{id}/address` (the just-shipped PATCH) — sub-resource of one property aggregate, scoped by category via query param.
- **Cost score override** lives at `PATCH /api/v1/admin/listings/properties/{property_id}` — the natural detail path of the admin listings collection. Patching the listing as a whole means future overridable derived signals (e.g. `featured_score`) slot in without new endpoints.

**Schema additions:**

- `property_amenities.manually_edited boolean default false` — new column.
- `property_listings.cost_score_manually_edited boolean default false` — new column.
- (no flag on `embedding` — derived, see below.)

**Re-enrichment respects edits:**

When the worker runs (manually clicked or batch-triggered), it scans for `manually_edited=true` rows in each category before refetching. Two policies, configurable via `_AppConstants.ENRICHMENT_RESPECTS_MANUAL_EDITS: bool = true`:

- `true` (default): per-category, if **any** row in the category is manually edited, the entire category is skipped on re-enrichment. Coarse but safe — never silently overwrites.
- `false`: re-enrich blindly. `force=true` on the command endpoint also bypasses this guard.

**Embedding stays derived:**

After any manual amenity or cost-score edit, the worker auto-fires a re-embed-only job (`ENRICH_PROPERTY_REQUESTED.v1` with `{stages: ["embedding"]}`). The embedding represents the listing's lifestyle profile; if the underlying amenities change, the vector should reflect that. We don't make agents trigger this manually.

### 4. Configurable settings infrastructure

Adopt the `db_constants.py` pattern (reference: `~/src/trialspark/protocol-research-service/core/db_constants.py`), adapted to SQLAlchemy. Lives in `src/shared/configurable_settings/`:

```python
# src/shared/configurable_settings/constants.py
class _Constants(BaseModel):
    """Runtime-editable settings. DB rows override these defaults."""
    # Provider selection
    PLACES_PROVIDER: Literal["google", "overpass", "gpt", "scrapingbee"] = "overpass"
    PLACES_PROVIDER_DISPLAY: Literal["google", "overpass"] = "google"  # for top-5 names
    EMBEDDING_PROVIDER: Literal["openai", "voyage"] = "openai"

    # POI discovery
    POI_RADIUS_METERS: int = 1500
    POI_CACHE_TTL_DAYS: int = 30

    # Cost-of-living model
    COST_MODEL_VERSION: str = "v1"
    COST_PER_ADULT_EUR_MONTH: int = 900
    COST_PER_CHILD_EUR_MONTH: int = 400
    # COST_PROXIMITY_WEIGHTS — defined in v4

    # Enrichment behavior
    ENRICHMENT_RESPECTS_MANUAL_EDITS: bool = True
    AUTO_ENRICH_ON_PUBLISH: bool = False  # promotion-path flag — see §5
```

```python
# src/shared/configurable_settings/loader.py
class _AppConstants:
    _values: _Constants | None = None
    _loaded_at: datetime | None = None
    _ttl: timedelta = timedelta(seconds=60)  # TTL refresh, not load-once

    async def values(self, session_factory) -> _Constants: ...
```

Two adaptations vs. the trialspark reference:

- **TTL-bounded refresh (60s default).** Trialspark's pattern reloads on every `set_values()` call — fine for batch jobs, too chatty on a hot HTTP path. TTL gives a middle ground: a row change in the DB takes effect within a minute, no redeploy.
- **Pydantic `Literal` types** for enumerated choices (`PLACES_PROVIDER`). A typo (`PLACES_PROVIDER=googlee`) raises at validation time, not silently falls through to a default.

The existing env-var-backed `Settings` class in `src/shared/config.py` stays — it owns boot-time config (DB URLs, AWS creds, Stripe keys). The new `_AppConstants` is for runtime-tunable product knobs. Different layers, different concerns.

### 5. Promotion path — `AUTO_ENRICH_ON_PUBLISH` flag

The flag exists in the schema with default `False`. When flipped to `True`:

- A new handler subscribes to `PROPERTY_PUBLISHED.v1` and fires the same `ENRICH_PROPERTY_REQUESTED.v1` command.
- No code change required to flip — just a row update in `configurable_settings`.
- Still command-driven under the hood; the projector is just one more caller of the command publisher.

This means we can ship v3 as fully manual, watch the cost data and quality signals, then flip auto-enrichment on later for paying tiers / specific orgs without re-architecting.

### 6. PlacesService factory + provider stubs

The `PlacesService` port stays as-is (`src/properties/application/ports/places_service.py`). Two real adapters at v3 launch:

- **`GooglePlacesService`** — exists, current default for the agent path. Stays as the "polish" tier (curated names, ratings) — used for `PLACES_PROVIDER_DISPLAY=google`.
- **`OverpassPlacesService`** — new, free OSM data. Default for `PLACES_PROVIDER=overpass` (the cost-scoring tier).

Two stub adapters with sharp warnings:

- **`GptSearchPlacesService`** — raises `NotImplementedError("LLM search hallucinates POIs without a grounding tool; enable in code first")`. The enum supports it so the match is exhaustive; the stub prevents accidental wiring.
- **`ScrapingBeePlacesService`** — raises `NotImplementedError("Scraping Google Maps violates Google ToS; legal/ops decision required")`.

A factory `get_places_service(constants, *, purpose: Literal["scoring", "display"]) -> PlacesService` reads the relevant config field at call time and returns the right adapter. Geo-cache is a decorator port wrapping any adapter, keyed by `(rounded_lat, rounded_lon, category, provider)` with TTL from `constants.POI_CACHE_TTL_DAYS`.

### 7. Updated consequences

- **No new SNS topic.** v1's `PROPERTY_LISTING_CREATED.v1` is gone.
- **One new command queue** (`property-enrichment-queue` + DLQ) — added to `scripts/localstack-init.sh` and prod SNS/SQS provisioning.
- **One new worker entrypoint** (`properties.entrypoints.enrichment_worker`) — added to README's worker list and the runbook.
- **One existing endpoint deprecated and replaced:** `POST /api/v1/admin/property-amenities/discover` → `POST /api/v1/admin/properties/{id}/enrich`. Cleans up the domain-event-as-command smell in the existing handler.
- **Schema growth:** `property_amenities` gains `manually_edited bool` and `place_type text`. `property_listings` gains `cost_score jsonb`, `cost_model_version text`, `cost_score_manually_edited bool`, `embedding vector(1536)`, `enriched_at timestamptz`, `enrichment_attempts int`. New table `configurable_settings (name text pk, value text, updated_at timestamptz)`.
- **`AmenityCategory`** gains the 9 new variants from v2 (alembic enum migration).
- **Two new ports:** `EmbeddingProvider` (listings), `ListingDerivedSignalsRepository` (listings — properties' worker writes through it). The v2-proposed `DiscoverAmenitiesForPropertyPort` / `GetAmenitiesForPropertyPort` go away — properties owns both the trigger and the data, so listings doesn't need to call back into properties for POI discovery anymore. The cross-context dependency reverses: properties now writes derived signals into listings via `ListingDerivedSignalsRepository`.
- **One new infrastructure module:** `src/shared/configurable_settings/` with the constants + loader.

## v4 — Canonical spec (supersedes v1-v3)

v1 through v3 capture the architectural reasoning trail. v4 is the version we implement against. Where v4 disagrees with v1-v3, v4 wins.

### Locked decisions

| #   | Decision                                                       | Notes                                                                                                                                                                                                                                                                                                                                                                            |
| --- | -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **Vocabulary is POI, not amenity**                             | "Amenity" implies a feature _of_ the property (gym in the building); POI is _near_ the property. The new workflow uses POI everywhere.                                                                                                                                                                                                                                           |
| 2   | **Existing amenity code stays untouched**                      | `PropertyAmenity`, `AmenityCategory`, `DiscoverPropertyAmenities`, `property_amenities` table, `POST /property-amenities/discover` endpoint — all stay as shipped, but are no longer invoked from any agent UI. Consolidation (rename or delete) is a separate cleanup ADR. **The new POI workflow is built fresh, parallel to the existing amenity code, not derived from it.** |
| 3   | **Manual command trigger only**                                | No event-driven path. No auto-on-publish flag. Agent clicks → command queued → worker runs. Per-property only, no bulk endpoint.                                                                                                                                                                                                                                                 |
| 4   | **Three workflow stages**                                      | (1) discover, (2) rank by category, (3) cost-of-life calculation. **Embedding deferred** but architected for via the embedding repository port (see §3.5).                                                                                                                                                                                                                       |
| 5   | **Properties owns POIs; listings owns the derived cost score** | Cross-context write through a callable Protocol port (`ListingDerivedSignalsRepository`).                                                                                                                                                                                                                                                                                        |
| 6   | **Configurable settings infrastructure**                       | DB-backed runtime config (`db_constants.py` pattern adapted to SQLAlchemy with TTL-bounded refresh). Carries from v3 §4.                                                                                                                                                                                                                                                         |
| 7   | **Multi-provider `PlacesService`**                             | Google + OSM real adapters; GPT/ScrapingBee stubs that raise. Geo-cache as decorator port. Carries from v3 §6.                                                                                                                                                                                                                                                                   |
| 8   | **Embedding storage in Pinecone, not pgvector**                | New decision. External managed vector DB. Repository port + adapter; embedding never lives in the SQL row.                                                                                                                                                                                                                                                                       |

### 1. Domain models — properties context

```python
# src/properties/domain/models/property_poi.py
class PoiCategory(str, enum.Enum):
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

@dataclass
class PropertyPoi:
    id: UUID
    property_id: UUID
    category: PoiCategory
    name: str
    distance_meters: float
    latitude: float
    longitude: float
    place_type: str | None = None              # underlying provider type (e.g. "subway_station")
    place_id: str | None = None                # provider-specific ID (Google place_id, OSM node id)
    metadata: dict = field(default_factory=dict)  # custom jsonb — agent-supplied or provider extras
    manually_edited: bool = False
    created_at: datetime = ...
    updated_at: datetime = ...
```

`metadata` is the "custom JSON" the user asked for: agent-defined keys (`school_type`, `notes`), provider extras (Google rating, OSM tags) — anything not first-class lands here.

### 2. HTTP surface

| Method + Path                                           | Purpose                                                  | Sync/Async  | Body                                                                                                  |
| ------------------------------------------------------- | -------------------------------------------------------- | ----------- | ----------------------------------------------------------------------------------------------------- |
| `POST /api/v1/admin/properties/{id}/enrich`             | Trigger the full workflow                                | Async (202) | `{"force": bool}` (default false)                                                                     |
| `POST /api/v1/admin/properties/{id}/pois`               | Replace the entire POI catalog (manual entry / override) | Sync        | `{"pois": [PropertyPoi-shaped objects with metadata jsonb]}` — all rows marked `manually_edited=true` |
| `GET /api/v1/admin/properties/{id}/pois`                | List the property's POIs (with metadata)                 | Sync        | —                                                                                                     |
| `PATCH /api/v1/admin/properties/{id}/pois/{poi_id}`     | Edit one POI in place                                    | Sync        | Subset of `PropertyPoi` fields. Sets `manually_edited=true`.                                          |
| `DELETE /api/v1/admin/properties/{id}/pois/{poi_id}`    | Remove one POI                                           | Sync        | —                                                                                                     |
| `PATCH /api/v1/admin/listings/properties/{property_id}` | Override `cost_score` (and other future derived signals) | Sync        | `{"cost_score": {...}}`. Sets `cost_score_manually_edited=true` on the listings row.                  |

All routes gated by `require_org_member` (or stricter role gates if product wants) — same pattern as the rest of the admin surface.

No bulk trigger endpoint. No auto-trigger from any event.

### 3. Use cases, services, ports

```
# Properties context — POI ownership + workflow
src/properties/application/use_cases/
├── enrich_property.py                   # orchestrator (consumed by worker)
├── replace_property_pois.py             # POST /pois — sync replace-all
├── update_property_poi.py               # PATCH /pois/{id} — single-row edit
├── delete_property_poi.py               # DELETE /pois/{id}
└── list_property_pois.py                # GET /pois
src/properties/application/services/
├── poi_discovery_service.py             # stage 1 — calls PlacesService, fans out per category
├── poi_ranking_service.py               # stage 2 — proximity-weighted ranking per category
└── cost_of_life_service.py              # stage 3 — pure function over (POIs, cost model)
src/properties/application/ports/
├── places_service.py                    # external POI provider (Google / OSM / ...) — already exists
├── listing_derived_signals_repository.py # cross-context write to listings (cost score)
└── embedding_provider.py                # embedding generation (deferred but port lives here for symmetry)

# Listings context — derived signals + their edit surface
src/listings/application/use_cases/
└── update_listing_cost_score.py         # PATCH /listings/properties/{id} — cost-score override
src/listings/application/ports/
├── embedding_repository.py              # NEW — Pinecone-backed vector storage (port; adapter follows)
└── listing_derived_signals_repository.py # implementation lives here (port surface in properties)
```

#### 3.1 Workflow orchestrator: `EnrichProperty`

```python
class EnrichProperty:
    """Orchestrates the three-stage POI enrichment workflow.

    Consumed by the worker on `ENRICH_PROPERTY_REQUESTED.v1`. Each stage
    is independently retryable — the orchestrator marks per-stage success
    in `property_pois.discovery_run_at` and `property_listings.cost_score`
    so a partial failure can resume cleanly.
    """
    def __init__(
        self,
        property_repo: PropertyRepository,
        poi_repo: PropertyPoiRepository,
        poi_discovery: PoiDiscoveryService,
        poi_ranking: PoiRankingService,
        cost_of_life: CostOfLifeService,
        derived_signals_repo: ListingDerivedSignalsRepository,
        constants: AppConstants,
    ): ...

    async def execute(self, *, property_id: UUID, force: bool, stages: list[str]) -> None: ...
```

#### 3.2 Stage 1 — `PoiDiscoveryService`

Fans out one `PlacesService.find_nearby` call per `(category, place_type)` pair (multi-type categories like `PUBLIC_TRANSIT` produce multiple calls), at concurrency=5 (existing pattern from `discover_property_amenities.py`). Returns raw `NearbyPlace[]` per category before ranking.

Respects `manually_edited` rows: if any row in a category is manually edited, the category is skipped on re-run unless `force=True`. Policy controlled by `_AppConstants.ENRICHMENT_RESPECTS_MANUAL_EDITS`.

#### 3.3 Stage 2 — `PoiRankingService`

Per-category proximity-weighted ranking. Keeps top-N (default `TOP_PLACES_LIMIT=5`, configurable). Pure function — no I/O.

#### 3.4 Stage 3 — `CostOfLifeService`

Pure function: `compute(pois: list[PropertyPoi], model: CostModel) -> CostScore`. Reads cost coefficients from `_AppConstants` (per-adult, per-child, per-category proximity weights). Returns a `CostScore` dataclass with the breakdown. Stored on `property_listings.cost_score` jsonb via the `ListingDerivedSignalsRepository`. Carries `cost_model_version` so re-scoring is selective.

Concrete formula sketch is **v5** territory.

#### 3.5 Embedding (deferred but architected)

```python
# src/listings/application/ports/embedding_repository.py
class EmbeddingMatch(BaseModel):
    property_id: UUID
    score: float
    metadata: dict[str, Any]

class EmbeddingRepository(Protocol):
    """Port over a vector store. Implementation owns provider details
    (Pinecone index name, namespace, dimensions, etc.) — domain code
    only knows about property_id, vectors, and matches.
    """
    async def upsert(
        self, *, property_id: UUID, embedding: list[float], metadata: dict[str, Any]
    ) -> None: ...
    async def search(
        self, *, query_embedding: list[float], top_k: int = 20, filter: dict | None = None
    ) -> list[EmbeddingMatch]: ...
    async def delete(self, *, property_id: UUID) -> None: ...
```

**Adapters:**

- `PineconeEmbeddingRepository` — production. Wraps the Pinecone client (`pinecone-client` Python SDK), reads `PINECONE_API_KEY`, `PINECONE_INDEX`, `PINECONE_NAMESPACE` from env (boot-time `Settings`, not runtime constants — these are infra credentials, not product knobs). Index dimensions match the `EmbeddingProvider` model output (default 1536 for OpenAI's `text-embedding-3-small`).
- `InMemoryEmbeddingRepository` — tests. Naive in-memory dict + cosine similarity in pure Python.

**Why Pinecone, not pgvector:**

- Managed service — no ops burden as the index grows.
- Built-in metadata filtering (filter by `organization_id`, `listing_status`, etc. at query time — no separate SQL join).
- Cosine similarity at high dimensions is what it's built for; pgvector works but ages worse at scale.
- Free tier covers initial volume; paid tiers scale linearly.
- Trade-off: external dependency, network call per query. Acceptable for search latency budgets.

**The `embedding` column does NOT exist on `property_listings`.** The vector lives in Pinecone, keyed by `property_id`. The SQL row gets one timestamp column: `embedding_synced_at timestamptz null` — null means embedding not yet generated, non-null means it's in Pinecone. That's the only Postgres-side embedding bookkeeping.

**When does embedding land?** Stage 4 of the workflow when the user opts to ship it. The `EmbeddingProvider` port + `EmbeddingRepository` port land in v4 (so the deferral isn't structural debt — the surface is in place); the actual stage 4 wiring is a follow-up.

### 4. Async transport

- New command type: `ENRICH_PROPERTY_REQUESTED.v1` carrying `{property_id, organization_id, force, stages?, requested_by_user_id}`.
- New SQS queue: `property-enrichment-queue` + `property-enrichment-dlq` with `maxReceiveCount=5` (matches every other command queue per ADR-008).
- New worker entrypoint: `properties.entrypoints.enrichment_worker --queue enrichment`.

### 5. Schema additions

#### 5.1 New table `property_pois`

```sql
CREATE TABLE property_pois (
  id              uuid PRIMARY KEY,
  property_id     uuid NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
  category        text NOT NULL,                    -- PoiCategory enum
  name            text NOT NULL,
  distance_meters double precision NOT NULL,
  latitude        double precision NOT NULL,
  longitude       double precision NOT NULL,
  place_type      text,                              -- "subway_station", "supermarket", ...
  place_id        text,                              -- Google place_id / OSM node id
  metadata        jsonb NOT NULL DEFAULT '{}'::jsonb,
  manually_edited boolean NOT NULL DEFAULT false,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX property_pois_property_id_idx ON property_pois(property_id);
CREATE INDEX property_pois_category_idx ON property_pois(category);
```

This table is **separate from the existing `property_amenities`**. v4 explicitly does not migrate or modify `property_amenities` — it stays exactly as today.

#### 5.2 `property_listings` additions

```sql
ALTER TABLE property_listings
  ADD COLUMN cost_score                 jsonb,
  ADD COLUMN cost_model_version         text,
  ADD COLUMN cost_score_manually_edited boolean NOT NULL DEFAULT false,
  ADD COLUMN embedding_synced_at        timestamptz,
  ADD COLUMN enriched_at                timestamptz,
  ADD COLUMN enrichment_attempts        integer NOT NULL DEFAULT 0;
```

No `embedding` column. Pinecone is the store.

#### 5.3 New table `configurable_settings`

```sql
CREATE TABLE configurable_settings (
  name       text PRIMARY KEY,
  value      text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
```

### 6. Configurable settings — keys for v4

```python
class _Constants(BaseModel):
    # POI provider
    PLACES_PROVIDER: Literal["google", "overpass", "gpt", "scrapingbee"] = "overpass"
    PLACES_PROVIDER_DISPLAY: Literal["google", "overpass"] = "google"
    POI_RADIUS_METERS: int = 1500
    POI_CACHE_TTL_DAYS: int = 30
    TOP_PLACES_LIMIT: int = 5

    # Cost-of-life model (formula details in v5)
    COST_MODEL_VERSION: str = "v1"
    COST_PER_ADULT_EUR_MONTH: int = 900
    COST_PER_CHILD_EUR_MONTH: int = 400

    # Enrichment behavior
    ENRICHMENT_RESPECTS_MANUAL_EDITS: bool = True
```

`AUTO_ENRICH_ON_PUBLISH` is **dropped**. Manual only.

### 7. Updated consequences (final list)

- **No new SNS topic.** v1's `PROPERTY_LISTING_CREATED.v1` is gone.
- **One new command queue** (`property-enrichment-queue` + DLQ).
- **One new worker entrypoint** (`properties.entrypoints.enrichment_worker`).
- **Two new tables:** `property_pois` (properties owns), `configurable_settings` (shared infra).
- **`property_listings` gains six columns** (cost score + bookkeeping; no embedding column).
- **External vector DB dependency:** Pinecone. New env vars (`PINECONE_API_KEY`, `PINECONE_INDEX`, `PINECONE_NAMESPACE`) in boot-time `Settings`. New Python dep (`pinecone-client`).
- **Five new ports** (per the §3 file list): `PoiRepository` (properties), `ListingDerivedSignalsRepository` (listings, cross-context surface), `EmbeddingProvider` (listings), `EmbeddingRepository` (listings), and `AppConstants` (shared). Plus the existing `PlacesService` (properties) reused. Each port has at least an in-memory adapter for tests.
- **Existing `property-amenities` surface stays as-is and unused.** Long-term consolidation deferred.

## v5 — Cost-of-life formula and `CostScore` data model

This iteration commits the concrete arithmetic for stage 3 of the workflow. Defined here, runtime-tunable via `_AppConstants` (per ADR §6).

### 5.1 Design principle: household-independent storage

The stored `CostScore` is a function of `(POIs, cost model)` — **household composition is NOT baked in**. Search-time queries combine the stored score with the user's household to produce a final monthly estimate.

Why: the cost components are independent. A property's transport surcharge doesn't change whether a couple or a family lives there. The base-per-adult and base-per-child are multipliers applied at search time. This means:

- **One stored score per listing**, valid for any household composition.
- **No cache invalidation on UI search-param changes** — agents typing `household=2A1C` doesn't recompute or re-fetch.
- **No re-scoring on filter UX changes** — the schema doesn't lock in any specific household preset.
- **Agents can still override the stored score** when they know the formula is wrong for their property — `cost_score_manually_edited=true` stops re-runs from clobbering it.

### 5.2 Data model

```python
# src/properties/domain/models/cost_score.py
@dataclass(frozen=True)
class CostScore:
    """Cost factors for one listing, stored on `property_listings.cost_score`.
    Household-independent. Search-time queries combine these with the user's
    household composition.
    """
    # Base costs (per-person, household-independent)
    base_per_adult_eur: Decimal
    base_per_child_eur: Decimal

    # Surcharges driven by POI proximity
    transport_surcharge_eur: Decimal           # applies to everyone (transit, grocery, pharmacy)
    family_surcharge_per_child_eur: Decimal    # applies per child (school, kindergarten)

    # Per-category contribution breakdown — for explainability in the UI
    # ("why is this listing more expensive than that one?")
    proximity_factors: dict[str, Decimal]      # category name -> €/month contribution

    # Versioning + provenance
    model_version: str
    computed_at: datetime


@dataclass(frozen=True)
class HouseholdComposition:
    """Search-time input. Not stored on listings."""
    adults: int = 1
    children: int = 0


def estimate_monthly_cost(score: CostScore, household: HouseholdComposition) -> Decimal:
    """Combine a stored CostScore with a household composition.
    Pure function. Cheap. Computed per-listing at search time.
    """
    return (
        score.base_per_adult_eur * household.adults
        + score.base_per_child_eur * household.children
        + score.transport_surcharge_eur
        + score.family_surcharge_per_child_eur * household.children
    )
```

### 5.3 The proximity-surcharge function

For each category that has a non-zero `weight`, the surcharge is a linear interpolation between two distance bands:

```python
def proximity_surcharge(
    distance_meters: float,
    weight_eur: Decimal,
    near_m: int,
    far_m: int,
) -> Decimal:
    """0 if at-or-closer-than `near_m`. Full `weight_eur` if at-or-farther-than
    `far_m`. Linear interpolation in between.
    """
    if distance_meters <= near_m:
        return Decimal(0)
    if distance_meters >= far_m:
        return weight_eur
    fraction = Decimal(distance_meters - near_m) / Decimal(far_m - near_m)
    return weight_eur * fraction
```

If a category has **zero POIs** discovered (and discovery completed successfully — see §7 for partial-failure handling), the property is treated as **at the `far_m` threshold** for that category — the worst case. A neighborhood without a single supermarket within 1.5 km legitimately incurs the full grocery surcharge.

### 5.4 Per-category weights (defaults — runtime-tunable)

Categories split into three bands based on what they affect:

| Category                                                                                                                             | Band             | Default weight (€/month, full surcharge) | Affects                                                                    |
| ------------------------------------------------------------------------------------------------------------------------------------ | ---------------- | ---------------------------------------- | -------------------------------------------------------------------------- |
| `PUBLIC_TRANSIT`                                                                                                                     | transport        | 80                                       | Everyone — flips household between "needs a car" and "doesn't"             |
| `GROCERY`                                                                                                                            | transport        | 30                                       | Everyone — frequent trips                                                  |
| `PHARMACY`                                                                                                                           | transport        | 10                                       | Everyone — occasional                                                      |
| `HOSPITAL`                                                                                                                           | transport        | 5                                        | Everyone — emergencies, rare                                               |
| `GAS_STATION`                                                                                                                        | transport        | 0                                        | Informational; absorbed by `PUBLIC_TRANSIT`                                |
| `SCHOOL`                                                                                                                             | family-per-child | 40                                       | Per child only — daily transfer                                            |
| `KINDERGARTEN`                                                                                                                       | family-per-child | 50                                       | Per child only — daily transfer                                            |
| `BANK`, `POST_OFFICE`, `LIBRARY`, `GYM`, `RESTAURANT`, `COFFEE_SHOP`, `BAKERY`, `LAUNDRY`, `SHOPPING_MALL`, `PARK`, `POLICE_STATION` | quality-of-life  | 0                                        | Surfaced for semantic search + filters; do not contribute to monetary cost |

The `quality-of-life` band rows have `weight=0` so they're computed (their proximity is recorded in `proximity_factors` for transparency) but contribute zero to `transport_surcharge_eur` or `family_surcharge_per_child_eur`.

### 5.5 The full computation, stage 3

```python
class CostOfLifeService:
    def compute(self, *, pois: list[PropertyPoi], constants: _Constants) -> CostScore:
        weights = constants.COST_PROXIMITY_WEIGHTS  # dict[str, int] from configurable settings
        near_m = constants.PROXIMITY_NEAR_METERS
        far_m = constants.PROXIMITY_FAR_METERS

        proximity_factors: dict[str, Decimal] = {}
        transport_surcharge = Decimal(0)
        family_surcharge_per_child = Decimal(0)

        for category in PoiCategory:
            weight = Decimal(weights.get(category.value, 0))
            if weight == 0:
                proximity_factors[category.value] = Decimal(0)
                continue

            nearest = min(
                (p for p in pois if p.category == category),
                key=lambda p: p.distance_meters,
                default=None,
            )
            if nearest is None:
                surcharge = weight  # worst case — no POI found in radius
            else:
                surcharge = proximity_surcharge(nearest.distance_meters, weight, near_m, far_m)

            proximity_factors[category.value] = surcharge

            if category in (PoiCategory.SCHOOL, PoiCategory.KINDERGARTEN):
                family_surcharge_per_child += surcharge
            else:
                transport_surcharge += surcharge

        return CostScore(
            base_per_adult_eur=Decimal(constants.COST_PER_ADULT_EUR_MONTH),
            base_per_child_eur=Decimal(constants.COST_PER_CHILD_EUR_MONTH),
            transport_surcharge_eur=transport_surcharge,
            family_surcharge_per_child_eur=family_surcharge_per_child,
            proximity_factors=proximity_factors,
            model_version=constants.COST_MODEL_VERSION,
            computed_at=datetime.now(timezone.utc),
        )
```

Pure function. No I/O. Deterministic given `(pois, constants)`. Trivially unit-testable.

### 5.6 Worked example

Property in central Lisbon. Discovery returned:

| Category                             | Distance to nearest |
| ------------------------------------ | ------------------- |
| `PUBLIC_TRANSIT` (Saldanha metro)    | 240 m               |
| `GROCERY` (Pingo Doce)               | 180 m               |
| `PHARMACY`                           | 150 m               |
| `HOSPITAL` (Hospital Curry Cabral)   | 1,100 m             |
| `SCHOOL` (Escola Marquesa de Alorna) | 600 m               |
| `KINDERGARTEN`                       | 400 m               |

Defaults: `near_m=500`, `far_m=2000`, weights as in 5.4. Costs `COST_PER_ADULT=900`, `COST_PER_CHILD=400`.

Surcharges:

- `PUBLIC_TRANSIT`: 240m ≤ near → 0
- `GROCERY`: 180m ≤ near → 0
- `PHARMACY`: 150m ≤ near → 0
- `HOSPITAL`: 1100m → fraction = (1100-500)/(2000-500) = 0.4 → 0.4 × 5 = 2
- `SCHOOL`: 600m → fraction = (600-500)/(1500) = 0.067 → 0.067 × 40 = 2.67
- `KINDERGARTEN`: 400m ≤ near → 0

Stored `CostScore`:

```json
{
  "base_per_adult_eur": "900.00",
  "base_per_child_eur": "400.00",
  "transport_surcharge_eur": "2.00",
  "family_surcharge_per_child_eur": "2.67",
  "proximity_factors": {
    "public_transit": "0.00",
    "grocery": "0.00",
    "pharmacy": "0.00",
    "hospital": "2.00",
    "school": "2.67",
    "kindergarten": "0.00"
  },
  "model_version": "v1",
  "computed_at": "2026-05-07T10:30:00Z"
}
```

Search-time estimates from this stored score:

| Household             | Calculation                  | Monthly estimate |
| --------------------- | ---------------------------- | ---------------- |
| 1 adult               | `1×900 + 0×400 + 2 + 0×2.67` | **€902**         |
| 2 adults              | `2×900 + 0×400 + 2 + 0×2.67` | **€1,802**       |
| 2 adults + 1 child    | `2×900 + 1×400 + 2 + 1×2.67` | **€2,205**       |
| 2 adults + 2 children | `2×900 + 2×400 + 2 + 2×2.67` | **€2,608**       |

Compare to a property in a less central area where `PUBLIC_TRANSIT=1800m` and `GROCERY=1600m`:

- `PUBLIC_TRANSIT`: 1800m → 0.867 × 80 = 69.36
- `GROCERY`: 1600m → 0.733 × 30 = 22.00

`transport_surcharge_eur` ≈ €91 + the small hospital + family surcharges. A family of 4 there pays ~€2,700, before considering rent. The signal is small in absolute terms but **comparative across listings is the point** — search ranking by total cost differentiates neighborhoods even when rents are similar.

### 5.7 Configurable settings additions

```python
class _Constants(BaseModel):
    # (existing v4 keys ...)

    # Cost-of-life — weights and thresholds
    COST_PROXIMITY_WEIGHTS: dict[str, int] = {
        "public_transit": 80,
        "grocery":        30,
        "pharmacy":       10,
        "hospital":       5,
        "school":         40,
        "kindergarten":   50,
        # all others default to 0 if absent from this dict
    }
    PROXIMITY_NEAR_METERS: int = 500
    PROXIMITY_FAR_METERS:  int = 2000
```

`COST_PROXIMITY_WEIGHTS` is stored as a JSON value in the `configurable_settings` table. Pydantic's `dict[str, int]` validator parses it on load.

When the formula or weights change in production, ops bumps `COST_MODEL_VERSION` and the next enrichment run re-stores the `CostScore` with the new version. Old rows can be selectively re-scored by querying `WHERE cost_model_version != 'v2'` and enqueueing the re-enrichment commands.

### 5.8 Limitations of v5 (explicit non-goals — defer to later iterations)

| Concern                                               | Reason for deferring                                                                                                                                                        |
| ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Quality / rating signal (Google ratings, OSM tags)    | Not modeled; nearest-distance is the only POI signal that drives cost. Quality lives in `metadata` jsonb and could weight the formula in a future iteration.                |
| POI density (5 supermarkets within 1 km vs 1 at 1 km) | Both have the same nearest-distance, so v5 treats them identically. Density-aware scoring is a future iteration.                                                            |
| Per-org weight overrides                              | `_Constants` is global. An agency that knows their region behaves differently can't override weights for their listings only. Per-org configurable settings is its own ADR. |
| Commute to work                                       | Not modeled — the user's workplace is unknown at scoring time. A search-time `work_location` parameter could add a per-query commute surcharge; not in v5.                  |
| Elderly-specific or disability-specific cost factors  | Out of scope.                                                                                                                                                               |

### 5.9 Edits — what happens when the agent overrides

When an agent calls `PATCH /api/v1/admin/listings/properties/{property_id}` with `{"cost_score": {...}}`:

1. The request body is validated against the `CostScore` schema.
2. The provided values overwrite the stored row.
3. `cost_score_manually_edited` flips to `true`.
4. The next enrichment run **skips stage 3** for this property unless `force=true` (or `_AppConstants.ENRICHMENT_RESPECTS_MANUAL_EDITS=false`).
5. Stages 1 and 2 (POI discovery + ranking) still run as normal — the agent's override is on the derived signal, not the underlying data.

This means agents can correct cost without losing future POI updates. Conversely, fixing a POI distance via `PATCH /pois/{poi_id}` and re-running enrichment **does** recompute cost (stage 3 runs unless cost was also manually edited).

## v6 — Schema migration plan

Three independent alembic migrations, each one feature-isolated so they can be reverted separately. All follow the project conventions visible in existing migrations (`alembic/versions/20260323_171315_e1f2a3b4c5d6_add_property_amenities_table.py` is the closest precedent — UUID-string PKs, `gen_random_uuid()` server default, `update_updated_at_column()` trigger, row-level security with service-role policy).

### 6.1 Migration 1 — `add_property_pois_table`

New table `property_pois`, fully independent of `property_amenities`. The two tables coexist; this migration does not touch `property_amenities`.

```python
"""add property_pois table

Revision ID: <fill in>
Revises:     <previous head>
Create Date: <generate>

Separate from `property_amenities` by design — stores one row per POI
(not one row per category-summary). See ADR-010 §4.2 for why.
"""

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    poi_category = sa.Enum(
        "hospital",
        "bank",
        "grocery",
        "school",
        "laundry",
        "coffee_shop",
        "pharmacy",
        "gym",
        "restaurant",
        "gas_station",
        "public_transit",
        "kindergarten",
        "park",
        "post_office",
        "library",
        "shopping_mall",
        "bakery",
        "police_station",
        name="poi_category",
    )

    op.create_table(
        "property_pois",
        sa.Column(
            "id",
            sa.UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("property_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("category", poi_category, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("distance_meters", sa.Float(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("place_type", sa.Text(), nullable=True),
        sa.Column("place_id", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "manually_edited",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Lookups: per-property, per-category, and the common "list this property's POIs" query.
    op.create_index(
        "idx_property_pois_property_id",
        "property_pois",
        ["property_id"],
        unique=False,
    )
    op.create_index(
        "idx_property_pois_property_category",
        "property_pois",
        ["property_id", "category"],
        unique=False,
    )

    # Re-uses the existing trigger function defined in the initial schema.
    op.execute("""
        CREATE TRIGGER update_property_pois_updated_at
            BEFORE UPDATE ON property_pois
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
    """)

    # Row-level security — same shape as property_amenities.
    op.execute("ALTER TABLE property_pois ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY property_pois_service_role
        ON property_pois FOR ALL USING (auth.role() = 'service_role');
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS property_pois_service_role ON property_pois")
    op.execute("DROP TRIGGER IF EXISTS update_property_pois_updated_at ON property_pois")
    op.drop_index("idx_property_pois_property_category", table_name="property_pois")
    op.drop_index("idx_property_pois_property_id", table_name="property_pois")
    op.drop_table("property_pois")
    op.execute("DROP TYPE IF EXISTS poi_category")
```

Notes:

- **No unique constraint** on `(property_id, category)` because v4 stores N POIs per category (top-N from ranking). Contrast with `property_amenities` which is one row per category (summary).
- **`metadata` defaults to `'{}'::jsonb`** so non-jsonb-aware writes (manual SQL, batch inserts) land cleanly.
- **`ondelete="CASCADE"`** on the FK — POIs vanish when the property is hard-deleted (matches `property_amenities` pattern).
- **No unique on `(property_id, category, place_id)`** even though it'd prevent dupes from re-runs. The de-duplication policy lives in stage 1 of the workflow (`PoiDiscoveryService` reconciles incoming with existing per `manually_edited` policy). Pushing dedup to a unique constraint would force the worker to handle conflict resolution at the SQL layer, which complicates the stage code without benefit.

### 6.2 Migration 2 — `add_listing_enrichment_columns`

Six columns added to `property_listings`. All nullable except the integer counter; existing rows get safe defaults.

```python
"""add listing enrichment columns

Revision ID: <fill in>
Revises:     <migration 1>
Create Date: <generate>
"""

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column(
        "property_listings",
        sa.Column("cost_score", sa.dialects.postgresql.JSONB, nullable=True),
    )
    op.add_column(
        "property_listings",
        sa.Column("cost_model_version", sa.Text(), nullable=True),
    )
    op.add_column(
        "property_listings",
        sa.Column(
            "cost_score_manually_edited",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "property_listings",
        sa.Column("embedding_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "property_listings",
        sa.Column("enriched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "property_listings",
        sa.Column(
            "enrichment_attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    # Operational query: "find listings that haven't been enriched recently / at all."
    # Partial index on the NULL case is the common monitoring pattern.
    op.create_index(
        "idx_property_listings_unenriched",
        "property_listings",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("enriched_at IS NULL"),
    )

    # Operational query: "find listings whose cost_score is on an old model version."
    # Cheap to maintain since cost_model_version changes only on formula bumps.
    op.create_index(
        "idx_property_listings_cost_model_version",
        "property_listings",
        ["cost_model_version"],
        unique=False,
        postgresql_where=sa.text("cost_model_version IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_property_listings_cost_model_version", table_name="property_listings")
    op.drop_index("idx_property_listings_unenriched", table_name="property_listings")
    op.drop_column("property_listings", "enrichment_attempts")
    op.drop_column("property_listings", "enriched_at")
    op.drop_column("property_listings", "embedding_synced_at")
    op.drop_column("property_listings", "cost_score_manually_edited")
    op.drop_column("property_listings", "cost_model_version")
    op.drop_column("property_listings", "cost_score")
```

Notes:

- **`cost_score` is jsonb, nullable.** NULL means "not yet computed" (or "discovery failed before stage 3"). The enrichment worker writes a value only after stage 3 succeeds — see v7 for partial-write handling.
- **Two partial indexes** chosen deliberately: full indexes on these columns would carry the non-target rows for no benefit. Backfill / monitoring queries hit the partial index; the regular search path doesn't.
- **No GIN index on `cost_score`** in v6. Search-time queries combine it with household composition arithmetic-ally (the v5 `estimate_monthly_cost` pure function); no jsonb-key lookup needed. If the search path later needs to filter on a specific `cost_score` field, a GIN-on-jsonb-path index is its own decision.
- **`embedding_synced_at` is nullable** — embedding lives in Pinecone, this column is bookkeeping only. NULL = vector not yet upserted to Pinecone, non-null = it's there.

### 6.3 Migration 3 — `add_configurable_settings_table`

Shared infrastructure for runtime-tunable config (see v3 §4 / v4 §6).

```python
"""add configurable_settings table

Revision ID: <fill in>
Revises:     <migration 2>
Create Date: <generate>

Runtime-tunable settings backing _AppConstants. Values are stored as
text and parsed to typed values via the Pydantic `_Constants` model
loader (TTL-bounded refresh, see ADR-010 v3 §4 and v4 §6).
"""

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.create_table(
        "configurable_settings",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("name"),
    )

    op.execute("""
        CREATE TRIGGER update_configurable_settings_updated_at
            BEFORE UPDATE ON configurable_settings
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
    """)

    # RLS: service role only. End-user sessions never touch this table.
    op.execute("ALTER TABLE configurable_settings ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY configurable_settings_service_role
        ON configurable_settings FOR ALL USING (auth.role() = 'service_role');
    """)


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS configurable_settings_service_role ON configurable_settings"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS update_configurable_settings_updated_at ON configurable_settings"
    )
    op.drop_table("configurable_settings")
```

Notes:

- **No seed data in the migration.** Defaults live in the Pydantic `_Constants` model. A row in `configurable_settings` is **only** created when ops wants to override a default. Migration creates an empty table; the loader treats absent rows as "use the default."
- **`value` is text.** The Pydantic model parses to typed values (int, bool, dict, Literal). JSON values (e.g. `COST_PROXIMITY_WEIGHTS`) are stored as JSON-encoded text and parsed on load.

### 6.4 Migration ordering and dependencies

The three migrations are independent in spirit but the file-level `down_revision` chain forces an order. Recommended:

```
[existing head] → add_property_pois_table → add_listing_enrichment_columns → add_configurable_settings_table
```

Reasons:

- `property_pois` first: it's the largest standalone change and the one most likely to need iteration during review (column choices, index choices). Putting it first means a revert of just-this-one is `alembic downgrade -1` from the post-3 state.
- `property_listings` columns second: depends on nothing from migration 1, but conceptually nearer (also enrichment-related).
- `configurable_settings` last: smallest, infrastructural, useful to the others but not depended on by them.

Independent migrations is the goal, but **order matters operationally**: if migration 2 fails in a deploy, the team can `downgrade -1` and the `property_pois` table remains useful; it's not an all-or-nothing.

### 6.5 What this migration plan does NOT do

Explicit non-goals to keep v6 honest:

- **Does not touch `property_amenities`.** v4 §2 commits to leaving the existing amenity surface untouched; v6 holds that line.
- **Does not seed any rows.** Empty tables, default behavior. Ops decides if/when to override `_Constants` defaults via `configurable_settings`.
- **Does not provision Pinecone.** Pinecone setup is out-of-band (managed-service signup, index creation, env var configuration). The DB migrations don't know about it.
- **Does not add the `property-enrichment-queue` SQS queue or DLQ.** That lives in `scripts/localstack-init.sh` for local dev and in the production SQS provisioning (Terraform / CDK / wherever the existing queues are managed). Schema migrations are SQL-only.
- **Does not migrate any data from `property_amenities` to `property_pois`.** They're different shapes (summary-per-category vs row-per-POI); a migration would be ambiguous (which row in `property_amenities.nearest_*` becomes the v4 single POI row? Or do we treat existing summaries as one POI per category? — neither answer is right). The existing `property_amenities` table stays as historical data; it's not the new system's source of truth.

## v7 — Failure modes, retry policy, freshness

This iteration commits the operational maturity layer. Where v5 said "stage X computes Y," v7 says "and when it fails, here's what happens."

### 7.1 Stage-by-stage failure surface

| Stage                   | What can fail                                                                                      | Failure mode                                                                                    |
| ----------------------- | -------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| 1. POI discovery        | External API (Google / Overpass / Pinecone for cache reads)                                        | Rate limit (429), timeout, 5xx, network error, auth error (401/403), permanent quota exhausted  |
| 2. Ranking              | Pure function over discovered POIs                                                                 | Only fails if input is malformed → programmer error, raises immediately                         |
| 3. Cost score           | Pure arithmetic + cross-context write to `property_listings` via `ListingDerivedSignalsRepository` | DB write failure (deadlock, connection drop, FK violation if listing was deleted mid-run)       |
| 4. (deferred) Embedding | OpenAI embedding generation → Pinecone upsert                                                      | Same provider failure modes as stage 1, plus Pinecone-specific (index full, dimension mismatch) |

Stage 2 is effectively infallible at runtime. Stages 1, 3, and (eventually) 4 are external-call-bound and need explicit handling.

### 7.2 Partial-write policy: save what works, retry the rest

When stage 1 partially succeeds (12 of 18 categories returned POIs, 6 hit transient errors):

- **Persist the 12.** Write them to `property_pois`. They're durable data; throwing them away wastes API quota.
- **Re-raise the worker.** SQS redelivers the command. `enrichment_attempts++` on the listing.
- **On the next attempt, stage 1 skips already-fresh categories.** A category is "fresh" if it has rows in `property_pois` whose `created_at` (or `updated_at`) is within the geo-cache TTL window. The retry only re-fetches the 6 that failed last time.
- **Stage 3 only runs when ALL 18 categories have rows.** Cost score is computed once we have a complete picture, not from a partial discovery.

This means a listing whose discovery flickered will accumulate POIs across attempts and only get a `cost_score` written once everything succeeds. The `enrichment_attempts` counter surfaces flaky areas to ops.

When stage 3 fails (POIs are saved but the cost-score write fails):

- **POIs persist** — they're already written.
- **Re-raise the worker.** Next attempt re-runs stage 3 only (stage 1 is a noop because all categories are fresh).
- **Cost is recomputable for free** from the saved POIs — no API quota burn on retry.

### 7.3 Cost score: NULL vs computed-with-zero-POIs (the user's flagged distinction)

Two visually-similar situations with completely different meanings:

| Situation                                                      | `cost_score`                                | `enriched_at` | What it means                                                                                                                                             |
| -------------------------------------------------------------- | ------------------------------------------- | ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Discovery never ran or failed before completing all categories | NULL                                        | NULL          | "We don't know yet." Filter out of cost-based search, OR show with a "not enriched" badge.                                                                |
| Discovery completed; some categories had zero POIs in radius   | computed (with full surcharges per v5 §5.3) | non-null      | "We checked; the area legitimately has no supermarket within 1.5 km." Worst-case surcharges apply. Include in cost-based search with the high cost shown. |
| Stage 3 failed even though stage 1 finished                    | NULL                                        | NULL          | "POIs are there but cost not yet computed." Treated as not-enriched until next retry succeeds.                                                            |
| Agent manually overrode                                        | agent's value                               | non-null      | `cost_score_manually_edited=true`. Treated as fully enriched. Future re-runs skip stage 3.                                                                |

Two invariants the worker enforces:

- **`enriched_at` is set ONLY when stage 3 successfully writes a (non-NULL) cost_score.** No partial-state ambiguity.
- **`cost_score` is NULL only when no value is yet computed.** The "everything is far / no POIs" case is a real number with a real `enriched_at`, not NULL.

Search-side query: `WHERE enriched_at IS NOT NULL` filters to enriched listings. `cost_score` is then guaranteed non-NULL on those rows.

### 7.4 SQS retry budget and DLQ workflow

Per ADR-008: every command queue gets a DLQ with `maxReceiveCount=5`.

- **Within a single worker attempt**, stage 1 wraps each external API call in tenacity-style retry with exponential backoff: cap 3 attempts per call, 1s / 4s / 16s delays, retry on 429 / 5xx / connection errors only. Auth errors (401/403) and 4xx-other re-raise immediately — they won't fix themselves.
- **Across worker attempts** (SQS redelivery), the budget is 5 attempts total before the message DLQs.
- **DLQ inspection** uses the existing `contract_intelligence`-style flag: `properties.entrypoints.enrichment_worker --queue enrichment-dlq` (matches `--queue ingestion-dlq` / `--queue analysis-dlq`). Ops re-runs DLQ messages via the same handler with verbose logging; persistent failures need a code fix before the retry will succeed.

Common DLQ root causes:

- Persistent provider outage (Google/OSM down for >5 retry windows — typically hours).
- Property hard-deleted between command publish and worker run → FK violation on `property_pois.property_id`. Fix: detect and drop.
- Bug in the worker (stage 1 schema change, unhandled response shape from a new place_type).
- Pinecone index dimension mismatch (only relevant after stage 4 ships).

### 7.5 Pinecone consistency model

Pinecone is eventually consistent on `upsert`. The vector becomes searchable typically within <1 second; documented worst case is "a few seconds." Implications:

- **Read-after-write is not guaranteed.** An agent who triggers enrichment, then immediately runs a semantic search, may not find the listing for ~1s. Acceptable: the semantic search use case is for end-users browsing, not for the agent verifying their click worked. The listing is visible everywhere else (`property_listings` is committed synchronously).
- **`embedding_synced_at` reflects OUR write time, not Pinecone's index time.** The column says "we successfully called upsert"; it doesn't say "search will return this row right now."
- **No explicit consistency guards in the worker.** We trust Pinecone's documented model. SQS-level retries cover harder failures (200 OK that didn't actually persist would never surface to us; we'd see real 5xx errors and retry).
- **Failure semantics**: stage 4 follows the same pattern as stage 1 — embed-and-upsert, retry on 429/5xx/network, re-raise everything else. `embedding_synced_at` is set on the success path; left NULL on failure.

### 7.6 Geo-cache invalidation

The decorator port wrapping `PlacesService` caches `(provider, rounded_lat, rounded_lon, category)` results for `POI_CACHE_TTL_DAYS` (default 30). Storage backend is intentionally unspecified in v7 — could be a Postgres `places_cache` table or Redis if we add Redis. Decoupled from this ADR.

Invalidation triggers:

| Trigger                                           | Behavior                                                                                                                                                    |
| ------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| TTL expiration                                    | Automatic. Cache lookups treat expired entries as misses.                                                                                                   |
| Provider switch (`PLACES_PROVIDER` config change) | Cache key includes `provider`, so different provider = different cache namespace. Old entries TTL out naturally. No explicit invalidation needed.           |
| Agent uses `force=true` on `/enrich`              | Bypasses the cache for THAT call only. Does not invalidate stored entries — the next caller without `force` still gets cached data.                         |
| Manual cache wipe                                 | No admin endpoint. If ops needs it, they delete rows directly. Adding a "wipe cache for this neighborhood" admin tool is a future call if it's ever needed. |

The cache key uses `rounded_lat, rounded_lon` (rounded to ~3 decimal places ≈ 100m granularity) so neighbors share cache entries. A property at (38.7421, -9.1503) and another at (38.7423, -9.1501) round to the same key and reuse the same Google call. This is the bulk of the cost reduction at scale.

### 7.7 Freshness / refresh policy

When does an existing enrichment become "stale"?

| Component                                                          | Staleness trigger                                                               | Policy                                                                                                                                                                       |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| POIs in `property_pois`                                            | After `POI_CACHE_TTL_DAYS` from `created_at`                                    | The CACHE expires; the STORED rows live forever until re-enrichment overwrites them. Manual re-trigger required to refresh.                                                  |
| `cost_score`                                                       | When `cost_model_version` doesn't match current `_Constants.COST_MODEL_VERSION` | Re-scoring is opt-in via the bulk path (operator runs `WHERE cost_model_version != 'v2'` queries to find candidates and enqueues commands). Not automatic on formula change. |
| Listing's lat/lon (very rare — usually only on address correction) | Implicit — old POIs become wrong                                                | No automatic detection in v7. Agent manually re-enriches after correcting the address.                                                                                       |
| Pinecone vector                                                    | When the source description changes substantially                               | No automatic detection. v8 (embedding wiring) decides whether description-edit triggers re-embed; v7 punts.                                                                  |

**Decision: no automatic re-enrichment in v7.** The system never spontaneously re-runs a successful enrichment. Re-runs happen only when:

1. Agent clicks `/enrich` on a property they own.
2. Operator runs a backfill query against the DB and enqueues commands directly.
3. (v8) A description PATCH triggers an `["embedding"]`-only re-run — but that's the only auto-trigger, and only for embedding.

A future optimization is a "stale enrichment" badge in the agent dashboard surfaced when `enriched_at < now() - 90 days`. v7 stores the timestamps so this is computable later; doesn't ship the UI.

### 7.8 What v7 does NOT specify

- **The geo-cache storage backend.** Postgres table vs Redis is a runtime infra call independent of this ADR. The cache decorator port is provider-agnostic.
- **Dead-letter alerting.** When messages DLQ, who gets paged? Falls under the broader observability story; out of scope for this ADR.
- **Cost dashboards.** Tracking Google Places spend per org / per day is an ops concern. Out of scope.

## Status: ready to flip to Accepted

v1-v3 captured the architectural reasoning trail. v4 commits the canonical design. v5 commits the cost formula. v6 commits the schema migrations. v7 commits the failure semantics.

The ADR is now complete enough to drive an implementation spec. **v8 (embedding stage wiring) is intentionally deferred** — it lands when product confirms semantic search ships, and the deferral has zero structural cost because the `EmbeddingProvider` and `EmbeddingRepository` ports are already in v4 §3.5.

## Iteration plan

- ~~v1, v2, v3~~ — superseded by v4.
- ~~v5: cost formula~~ — landed.
- ~~v6: schema migrations~~ — landed.
- ~~v7: failure modes~~ — landed above.
- **v8: Embedding stage wiring** — when product confirms semantic search ships. `EmbeddingProvider` adapter (OpenAI), `PineconeEmbeddingRepository` adapter, stage 4 in the orchestrator. Decoupled from v4-v7; can land anytime.

Status flips to **Accepted** on ADR review. Next step: open the implementation spec under `.claude/specs/active/2026-05-property-poi-enrichment.md` (or similar slug).
