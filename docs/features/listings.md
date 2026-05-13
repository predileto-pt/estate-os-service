# Listings

The `listings` bounded context exposes public, read-only property listings. It reads the same database tables as `properties` but defines its own ORM models to keep the boundary explicit. There is no authentication on these endpoints — they back the public property search portal.

**Source:** `src/listings/`

## Domain entities

| Entity                    | Description                                                                                                                    |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `ListedProperty`          | Read-only view of a property. Includes characteristics, prices, images. **No owners** — owner data is private to `properties`. |
| `PropertyCharacteristics` | Frozen value object: area, bedrooms, bathrooms, year built, energy rating, etc.                                                |
| `PropertyPrice`           | Frozen value object: amount + listing type.                                                                                    |
| `PropertyImage`           | Frozen value object: S3 key, filename, ordering.                                                                               |

Enums (defined locally — duplicated by design from `properties`):

- `ListingType` — `SALE` / `PURCHASE`
- `Typology` — `HOUSE` / `APARTMENT` / `LAND` / `RUIN`
- `PropertyStatus` — `DRAFT` / `ACTIVE` / `SOLD` / `RENTED` / `WITHDRAWN`

## Feature catalog

| Feature                                                       | Trigger                                         | Purpose                                                              |
| ------------------------------------------------------------- | ----------------------------------------------- | -------------------------------------------------------------------- |
| [GetProperty](#getproperty)                                   | `GET /api/v1/listings/properties/{property_id}` | Return one active property by ID                                     |
| [ListProperties](#listproperties)                             | `GET /api/v1/listings/properties`               | Filter and paginate active properties (public)                       |
| [ListOrgActiveListings](#listorgactivelistings)               | `GET /api/v1/admin/listings/properties`         | Same shape, scoped to caller's org via `require_org_member` (admin)  |

---

## Feature details

### GetProperty

Return a single active property. Returns 404 if not found or not active.

- **Inputs:** `property_id`
- **Output:** `ListedProperty`
- **Side effects:** none (read-only). The route handler generates pre-signed S3 download URLs for images at response time.
- **Source:** `src/listings/application/use_cases/get_property.py`

### ListProperties

Cursor-paginated active listings filtered by listing type, typology, parish/municipality/district, and price range. Used by the public portal (`GET /api/v1/listings/properties` with `q` empty).

- **Inputs:** `fp` (filter fingerprint from the route), `PropertyFilters`, `cursor: ListCursor | None`, `limit`
  - `listing_type?`, `typology?`, `min_price?`, `max_price?`
  - `parish?` / `municipality?` / `district?` — exact match on the structured columns
  - `limit` (1–20, default 20)
- **Output:** `CachedPage(items, next_cursor)` — `next_cursor` is the already-encoded token string, `None` at the tail
- **Pagination:** keyset on `(created_at DESC, id DESC)` via `list_active_keyset`. No `COUNT(*)` query — the response drops `total` entirely.
- **Caching:** TTL-only (default 90s, off by default behind `LISTINGS_PAGE_CACHE_ENABLED`). Cache key = `listings:list:v1:{fp}:{cursor_pos}:{limit}` so a different `limit` is a different cached page. Wired in front via the `ListingsPageCache` port (Null / InMemory / Redis adapters under `src/listings/adapters/cache/`).
- **Documented keyset invariant:** rows inserted with `created_at` newer than the head visible at first request do NOT appear on later pages of the same cursor chain. FE refresh = new cursor chain.
- **Source:** `src/listings/application/use_cases/list_properties.py`. ADR-016 + spec `2026-05-listings-cursor-pagination-and-page-cache`.

### ListOrgActiveListings

Admin variant of `ListProperties` scoped to the caller's organization. Mounted at `/api/v1/admin/listings` via a sibling `admin_router` in the same routes file (`src/listings/adapters/api/routes/listings.py`) — the URL prefix matches the rest of the admin surface (`admin/properties`, `admin/property-owners`, …) and keeps the public `/api/v1/listings/...` surface unchanged.

- **Auth:** `Depends(require_org_member)` — 401 if no auth, 403 if the caller isn't a member of `organization_id`. The use case itself is permission-agnostic.
- **Inputs:** `organization_id` (query) plus the same `PropertyFilters` as the public endpoint
- **Output:** `(list[ListedProperty], int)` — same shape as the public endpoint, so the agencies-dashboard can render the same card component
- **Status filtering:** the SQLAlchemy adapter's `WHERE status = ACTIVE` predicate (`_build_query`) is the canonical enforcement. The in-memory adapter cannot filter by status (`ListedProperty` has no `status` field) and is org-scope-only — see `list_active_for_organization`'s docstring for context.
- **Source:** `src/listings/application/use_cases/list_org_active_listings.py`, route at `src/listings/adapters/api/routes/listings.py` (`admin_router`).

## Read-model pattern

`listings` reads the `properties`, `property_prices`, and `property_images` tables but defines its own SQLAlchemy models in `src/listings/adapters/database/models.py` (`ReadPropertyModel`, `ReadPropertyPriceModel`, `ReadPropertyImageModel`) with `__table_args__ = {"extend_existing": True}`. This avoids cross-context imports while keeping a single physical schema.

The route layer (`src/listings/adapters/api/routes/listings.py`) calls `DocumentStorage.get_download_url()` for each image to produce signed URLs at response time — image bytes are never proxied through the API.

## Container

`src/listings/container.py` wires `GetProperty` and `ListProperties`. Built in `src/shared/entrypoints/bootstrap.py::get_listing_container()` and stored on `app.state.listing_container`.

### Session scope: one `AsyncSession` per repo method

`SqlAlchemyListingRepository` and `SqlAlchemyPropertyListingRepository` take an `async_sessionmaker[AsyncSession]`, not a single `AsyncSession`. Every public method opens its own scoped session via `async with self._session_factory() as session: …` and commits on success.

Why: the listings worker handles many events in sequence on the same process. Sharing a long-lived `AsyncSession` across handlers causes `MissingGreenlet: greenlet_spawn has not been called; can't call await_only() here` when ORM objects loaded in one operation are accessed under a different async/greenlet context. The same hazard sits behind the read API — concurrent FastAPI requests must not share a session. Per-method scoping is the simplest fix: every event handler and every API request gets a fresh session, and there's no cross-event ORM state to leak.

`update_location` and `increment_enrichment_attempts` call `session.refresh(model)` after `commit()` so the subsequent `_to_domain` attribute reads stay inside the active connection scope.

## Publishing a property

A property starts in `DRAFT` status and is invisible to the portal (the read endpoints filter `WHERE status = ACTIVE`). An agent publishes it via:

```
POST /api/v1/admin/properties/{property_id}/publish?organization_id={org_id}
```

- **Auth:** caller must be `OWNER` or `ADMIN` of the organization.
- **Preconditions** (all enforced at the domain level; a 422 response carries the list of missing codes):
  - `address` is non-empty
  - at least one `PropertyPrice`
  - at least one `PropertyOwner`
  - at least one `PropertyImage`
  - `status` is `DRAFT` or `WITHDRAWN` (re-publishing a `SOLD` / `RENTED` / `ACTIVE` row returns 422 with `cannot_publish_from_status:<current>`)

On success:

1. The `properties.status` column flips to `ACTIVE`.
2. `aggregate_version` is bumped (drives projector idempotency).
3. `PROPERTY_PUBLISHED.v1` is emitted with the standard `build_property_snapshot` payload — the same shape as `PROPERTY_CREATED.v1` / `PROPERTY_UPDATED.v1`, so the listings projector upserts the `property_listings` row via the same code path.
4. The property appears in the public `GET /api/v1/listings/properties` results on the next read.

Error responses:

| Code  | When                                                                                                                 |
| ----- | -------------------------------------------------------------------------------------------------------------------- |
| `401` | No / invalid auth token                                                                                              |
| `403` | Caller is a member but not `OWNER` / `ADMIN`                                                                         |
| `404` | Property id not found, or doesn't belong to `organization_id`                                                        |
| `422` | `{"message": "...", "reasons": ["missing_price", "missing_image", "cannot_publish_from_status:sold", ...]}`          |

**Source:** `src/properties/application/use_cases/publish_property.py`, route at `src/properties/adapters/api/routes/properties.py`.

## Running the listings events worker

The listings context has its own SQS worker that consumes carried-state property events and maintains the `property_listings` read-model. Run it locally with:

```bash
uv run python -m listings.entrypoints.events_worker
```

It consumes seven SNS topics via a single `listings-events-queue` — four upstream `PROPERTY_*.v1` events from the properties context, plus three listings-internal fan-out events for handler isolation (per ADR-008 §6):

| Event type                                      | Handler                       | Effect                                                                                                   |
| ----------------------------------------------- | ----------------------------- | -------------------------------------------------------------------------------------------------------- |
| `PROPERTY_CREATED.v1`                           | `handle_property_event`       | Insert a `property_listings` row from the carried-state snapshot.                                        |
| `PROPERTY_UPDATED.v1`                           | `handle_property_event`       | Upsert (newer `aggregate_version` wins). POIs preserved when the snapshot omits `pois`.                  |
| `PROPERTY_DELETED.v1`                           | `handle_property_event`       | Delete the row (version-guarded). Then publishes `PROPERTY_LISTING_DELETED.v1`.                          |
| `PROPERTY_PUBLISHED.v1`                         | `handle_property_event`       | Upsert with `status='active'` from the snapshot — same code path as CREATED / UPDATED.                   |
| `PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT.v1`  | `handle_address_enrichment`   | Call the LLM address parser and fill `parish` / `municipality` / `district`.                             |
| `PROPERTY_LISTING_UPDATED.v1`                   | `handle_listing_embedding`    | Compose canonical text, hash-check, embed via OpenAI, upsert vector to Pinecone, set `embedding_status`. |
| `PROPERTY_LISTING_DELETED.v1`                   | `handle_listing_deleted`      | Delete the listing's vector from the Pinecone namespace.                                                 |

After every applied projector upsert, `handle_property_event` publishes both `PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT.v1` (the existing precedent) and `PROPERTY_LISTING_UPDATED.v1` (new — spec `2026-05-listing-semantic-search`). Each lands on its own SNS topic so a poisoned LLM call DLQs only the address-enrichment event, an embedding failure DLQs only the embedding event, and the projected row stays alive throughout.

Worker uses the shared `EventBusWorker` (ADR-008). On RabbitMQ, the broker-side `consumer_timeout` (default 30 min) is the upper bound for handler runtime — comfortably above today's enrichment p99. See [ADR-008 addendum](../adr/008-event-bus-ports-and-fanout.md#addendum--2026-05-13-rabbitmq-as-the-active-transport).

See the shared worker pattern in the root `README.md` → *Domain events* section.

## Semantic-search indexing pipeline

ADR-013 phase 1 — write path only. Every published `property_listings` row gets embedded into a Pinecone namespace and kept in sync as `PROPERTY_*.v1` events flow. No public-facing endpoint changes; the read path (`q=` query parameter, two-stage retrieval) ships in a follow-up spec.

### Architecture

```
PROPERTY_PUBLISHED.v1 / PROPERTY_UPDATED.v1 / PROPERTY_DELETED.v1
        │
        ▼
listings worker  ──►  handle_property_event (projector)
                          ├─ upsert property_listings (incl. pois jsonb column)
                          └─ publish PROPERTY_LISTING_UPDATED.v1 to SNS
                                                  │
                                                  ▼
                                       handle_listing_embedding
                                       ├─ compose canonical text from row + POIs
                                       ├─ hash check (skip if (hash, version, model) unchanged)
                                       ├─ EmbeddingProvider.embed (OpenAI text-embedding-3-small)
                                       ├─ VectorIndex.upsert (Pinecone, vector + metadata)
                                       └─ update embedding_text_hash + embedded_at + status=INDEXED
```

### Canonical text schema (`LISTING_CANONICAL_TEXT_V1`)

A deterministic, labeled, line-oriented rendering of the row fed to the embedder. Hash stability is load-bearing: the embedding handler skips re-embedding when the persisted `(text_hash, version, model)` tuple matches.

```
LOCATION: <parish> · <municipality> · <district>
LISTING_TYPE: SALE | PURCHASE
TYPOLOGY: HOUSE | APARTMENT | LAND | RUIN
SIZE: <bedrooms> bed · <bathrooms> bath · <area_m2> m²
BUILT: <year_built> · energy <energy_rating>
PRICE: <price_eur> EUR
NEARBY: school: Escola X (0.2km), grocery: Pingo Doce (0.4km), …
DESCRIPTION: <description, truncated to MAX_DESCRIPTION_CHARS>
```

POI rendering invariants (locked at v1, in `src/listings/application/services/canonical_text.py`):

- **Filter-before-render** — POIs outside the category allowlist or beyond `LISTING_POI_MAX_DISTANCE_M` are dropped.
- **Deterministic ordering** — sort by `(category, distance_rounded_to_100m, name.lower())`.
- **Distance-precision rounding** — 100m buckets so re-geocoding jitter <100m can't invalidate the hash.
- **Hard cap** — `LISTING_POI_MAX_COUNT` (default 20) per listing.

Any rendering change is a `LISTING_CANONICAL_TEXT_V2` bump, not an in-place edit.

### Embedding state — `embedding_status` column

Every row carries an `embedding_status` enum (CHECK constraint, default `'PENDING'`):

| Status     | Meaning                                                                                                |
| ---------- | ------------------------------------------------------------------------------------------------------ |
| `PENDING`  | Row exists; embedding not yet attempted (or gate disabled).                                            |
| `INDEXED`  | Vector + metadata are live in the Pinecone namespace; `embedding_text_hash` matches the canonical text. |
| `FAILED`   | An embed or upsert call raised. SQS will redrive; on terminal failure ops investigates.                |

Embedding columns (`embedding_text_hash`, `canonical_text_version`, `embedding_model_version`, `embedded_at`, `embedding_status`) are owned by the embedding handler — the projector excludes them from its upsert SET clause so a `PROPERTY_UPDATED.v1` doesn't regress embedding state.

### Ops queries

```sql
-- Listings not yet indexed (uses partial index idx_property_listings_embedding_status_pending)
SELECT id, organization_id, embedding_status, updated_at
FROM property_listings
WHERE embedding_status != 'INDEXED'
ORDER BY updated_at DESC;

-- Stuck FAILED rows
SELECT id, embedding_status, updated_at
FROM property_listings
WHERE embedding_status = 'FAILED';
```

### Provisioning + rollout

Pinecone index creation, API-key management, end-to-end verification, and the model-bump playbook are documented in the [root README → Listings Semantic Search Setup](../../README.md#listings-semantic-search-setup). TL;DR:

1. Create a serverless Pinecone index named `listings-prod` (or whatever `PINECONE_INDEX` is set to), `1536` dimensions, `cosine` metric.
2. Copy the API key into `PINECONE_API_KEY`.
3. Set `LISTINGS_EMBEDDING_ENABLED=true` and restart the listings worker.

The pipeline is gated by `LISTINGS_EMBEDDING_ENABLED` (default `false`). When off, the embedding handler is a no-op — messages are still consumed (no DLQ buildup) but no embed/upsert work runs and `embedding_status` stays `PENDING`. Bootstrap doesn't even construct the OpenAI/Pinecone adapters in this mode, so a missing `PINECONE_API_KEY` with the gate off won't crash the worker.

A separate spec ships the backfill CLI under `src/listings/entrypoints/backfill_embeddings.py` for pre-existing rows.

### Environment variables

| Variable                        | Description                                                                                                                  | Default                                       |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| `LISTINGS_EMBEDDING_ENABLED`    | Master gate. When `false`, embedding handler is a no-op.                                                                     | `false`                                       |
| `EMBEDDING_MODEL`               | OpenAI embedding model. Used as `embedding_model_version` on the row.                                                        | `text-embedding-3-small`                      |
| `EMBEDDING_DIMENSIONS`          | Vector dimensions. Must match the model.                                                                                     | `1536`                                        |
| `VECTOR_INDEX_PROVIDER`         | Backing store selector. Today only `pinecone` is wired in production; the in-memory adapter ships for tests + local dev.    | `pinecone`                                    |
| `VECTOR_INDEX_NAMESPACE`        | Pinecone namespace = embedding model version. A model bump means: build a new namespace, validate, atomically flip this var. | `openai-text-embedding-3-small-v1`            |
| `PINECONE_API_KEY`              | Pinecone API key (required when `LISTINGS_EMBEDDING_ENABLED=true`).                                                          | —                                             |
| `PINECONE_HOST`                 | Direct host URL (e.g. `listings-prod-abc123.svc.aped-1234-xyz.pinecone.io`). Preferred — skips a control-plane RTT at startup. | —                                             |
| `PINECONE_INDEX`                | Index name. Fallback when `PINECONE_HOST` is empty (lazy host lookup) and used by ops scripts.                               | `listings-prod`                               |
| `PINECONE_CLOUD` / `PINECONE_REGION` | Informational — used when provisioning the index. Runtime adapter doesn't read these.                                    | `aws` / `us-east-1`                           |
| `LISTING_POI_MAX_COUNT`         | Hard cap on POIs rendered into `NEARBY:`.                                                                                    | `20`                                          |
| `LISTING_POI_MAX_DISTANCE_M`    | POIs further than this are dropped from `NEARBY:`.                                                                           | `3000`                                        |
| `LISTING_DESCRIPTION_MAX_CHARS` | Suffix-clip the description for the embedding.                                                                               | `2000`                                        |

### Sources

- ADR: [`docs/adr/013-listing-semantic-search.md`](../adr/013-listing-semantic-search.md)
- Spec: `.claude/specs/active/2026-05-listing-semantic-search.md`
- Composer: `src/listings/application/services/canonical_text.py`
- Handler: `src/listings/adapters/workers/embedding_handler.py`
- Pinecone adapter: `src/listings/adapters/vector/pinecone_index.py`
- OpenAI adapter: `src/listings/adapters/embedding/openai_provider.py`
- In-memory test doubles: `src/listings/adapters/vector/inmemory_index.py`, `src/listings/adapters/embedding/stub_provider.py`

## Search read path (ADR-013 phase 2 → ADR-014 hybrid retrieval)

ADR-013 phase 2 shipped the read path behind `LISTINGS_SEARCH_ENABLED=false`. ADR-014 (spec `2026-05-listing-search-structured-extraction`) refactors it in place to hybrid retrieval: structural facets extracted from the query become SQL filters; the residue rides cosine. Same gate, same response API plus two new fields on q-set responses (`matched_pois`, `unmatched_pois`).

### Endpoint behavior matrix

| Request                                            | Path taken                                                                                          | Notes                                                                                              |
| -------------------------------------------------- | --------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `GET /properties` (no `q`)                          | Existing structured-filter path (ADR-010), unchanged.                                                | Location filter optional. No regressions. `matched_pois` / `unmatched_pois` serialize as `[]`.    |
| `GET /properties?q=…` (no location)                 | **422** with `detail.code = "location_required_for_search"`.                                         | FE selector should never let the user submit this — defense in depth.                              |
| `GET /properties?q=…&parish=…` (gate off)           | Falls through to the structured-filter path. `q` silently ignored.                                  | Ship-safe default — `LISTINGS_SEARCH_ENABLED=false` works on prod from day one.                    |
| `GET /properties?q=…&parish=…` (gate on)            | `SearchListings` hybrid pipeline (extract → parallel(SQL pre-filter, embed) → ANN → hydrate).        | Vector-ranked candidates, NULL-data rows at the bottom, matched/unmatched POIs on the response.   |
| `GET /locations`                                    | `ListLocations` — country → district → municipality → parish tree, served from a bundled JSON catalog. | No DB dependency; full PT geography from day one. See `src/listings/static_data/locations.json`. |

### Search pipeline (ADR-014)

```
GET /properties?q=…&parish=…
   │
   ▼
 normalize_query (.strip(), whitespace-only → None)
   │
   ├── q normalized to None → list_properties.execute() (structured)
   │
   └── q set
         │
         ▼
       validate_location_for_search (422 if no parish/municipality/district)
         │
         ▼
       SearchListings.execute(query, location, filters)
         │
         ├── 1. QueryExtractor.extract → ParsedQuery
         │       (try/except → ParsedQuery(free_text_remainder=query))
         ├── 2. asyncio.gather(return_exceptions=True):
         │       ├── list_ids_for_search → list[UUID] candidates (SQL)
         │       └── EmbeddingProvider.embed(canonical-text-v3 render)
         │       SQL fails → broad mode. Embed fails → _relational_fallback.
         ├── 3. Cardinality guard:
         │       ├── normal (|cands| < cap):  filter=AND(status, listing_id IN [cands])
         │       └── broad  (|cands| == cap): filter=status, top_k × overshoot, intersect after
         │       Vector fails → _relational_fallback.
         ├── 4. list_by_ids hydrate (WHERE id = ANY(:ids) AND status='active')
         └── 5. _partition_and_rank: matched rows first, partial-data
                rows (≥1 criterion NULL on the row) last. Paginate.
         │
         ▼
       returns (rows, total, parsed) — parsed.nearby_pois drives
       the matched/unmatched POI composition in the route helper.
```

`_relational_fallback` reuses the SQL candidates (the parallel stage's first result) and skips ANN ranking. Sort by `(created_at desc, id desc)` within matched/partial buckets so the order is deterministic when cosine isn't available.

### `ParsedQuery` field map

The `QueryExtractor` (`gpt-4o-mini` via LangChain structured output, internal `_ExtractorResult` Pydantic envelope) populates the following fields from the raw query:

| Field | Source intent | Filter consumer |
|---|---|---|
| `typology` | "casa", "apartamento", "terreno", "ruína" | SQL hard filter on `typology` (route param wins on conflict) |
| `min_bedrooms` | "T2"/"T3"/"3 quartos" | SQL soft-hard on `num_of_bedrooms` (NULL admitted) |
| `min_bathrooms` | "2 wcs"/"2 casas de banho" | SQL soft-hard on `num_of_bathrooms` |
| `min_area_m2` / `max_area_m2` | "pelo menos 100m²"/"até 200m²" | SQL soft-hard on `area_in_m2` |
| `min_price` / `max_price` | "a partir de 250k"/"até 500k" | SQL soft-hard on `min_price` (route wins on conflict) |
| `has_pool` / `has_garden` / `has_elevator` / `has_parking` | "piscina"/"jardim"/"elevador"/"garagem" (True only — negation conservatively ignored) | SQL soft-hard on the matching column |
| `nearby_pois` | "escola"/"ginásio"/"supermercado"/etc. mapped to the closed `PoiCategory` enum | Embedded into `NEARBY:` line + drives matched/unmatched response |
| `free_text_remainder` | Everything left after extraction (off-vocab POIs, qualifiers like "jeitoso", "varanda") | Embedded into `DESCRIPTION:` line — pure cosine signal |

### Matched / unmatched POIs on the response

When `q` is set the response gains two fields (ALWAYS present; `[]` when q is empty):

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
      "reviews": [ … ]
    }
  ],
  "unmatched_pois": ["gym"],
  …
}
```

`matched_pois` is sorted ascending by `distance_meters` (the route helper sorts explicitly; the projection's `prop.pois` is in discovery order, not distance order). `unmatched_pois` carries the categories the user asked for that the listing doesn't have nearby — UX renders them as "you asked for: gym (not nearby)".

The rich POI fields (`address`, `image_urls`, `reviews`) flow from `PropertyPoi` through the snapshot (`build_property_snapshot` in `properties/application/events/property_event.py`) into `ListingPoi` on the projection.

### Read path env vars

| Variable                                    | Description                                                                                  | Default       |
| ------------------------------------------- | -------------------------------------------------------------------------------------------- | ------------- |
| `LISTINGS_SEARCH_ENABLED`                   | Master gate. When `false`, `?q=…` is silently ignored and the structured-filter path runs.   | `false`       |
| `SEARCH_LLM_MODEL`                          | `QueryExtractor` LLM. Cheap PT-capable default.                                              | `gpt-4o-mini` |
| `SEARCH_LLM_TIMEOUT_SECONDS`                | Per-call timeout for the extractor. On timeout, fall back to `ParsedQuery(free_text_remainder=query)`. | `4.0`  |
| `SEARCH_LLM_MAX_OUTPUT_TOKENS`              | Hard cap on extractor output.                                                                | `200`         |
| `LISTINGS_SEARCH_RANKED_LIST_SIZE`          | Cap on the ranked id list cached per `(q, filters)`. Renamed from `VECTOR_INDEX_TOP_K` in ADR-016. | `200`         |
| `SEARCH_MAX_PRE_FILTER_CANDIDATES`          | Cap on the SQL pre-filter result. `len == cap` → cardinality guard switches to broad-mode.   | `1000`        |
| `SEARCH_BROAD_MODE_OVERSHOOT`               | Multiplier on Pinecone `top_k` in broad mode (overshoot, then post-intersect with candidates). Final response is still capped to top_k. | `4`           |
| `LISTINGS_PAGE_CACHE_ENABLED`               | Master switch for the listings page cache (Redis). Off by default; Null adapters wired when off so call sites stay structurally identical. | `false`       |
| `LISTINGS_PAGE_CACHE_TTL_SECONDS`           | TTL for both `ListingsPageCache` and `SearchResultCache` entries.                            | `90`          |
| `REDIS_URL`                                 | Connection string for the shared Redis client.                                               | `redis://localhost:6379/0` |

### Pagination semantics

The public endpoint is cursor-paginated (ADR-016). Two modes share the same `?cursor=`/`limit=` interface:

- **List mode** (`?q` empty): `?cursor=` encodes a keyset position `(created_at, id)`; arbitrary depth.
- **Search mode** (`?q` set): `?cursor=` encodes an offset into the cached ranked id list. Depth bounded at `LISTINGS_SEARCH_RANKED_LIST_SIZE` (default 200) — past that, `next_cursor: null`. The bound is a deliberate product call (vector relevance at rank 200 is noise; users rarely scroll that far).

Cache hits skip both the LLM call AND the Pinecone call. Cache miss runs the full pipeline once per `(q, filters)` per TTL window and caches `(parsed, ranked_ids)` atomically — subsequent pages of the same search just `list_by_ids` the slice.

**Search-path cache-expiry invariant:** if the ranked-id-list cache expires mid-scroll, the next page miss re-fetches Pinecone; ranking may differ slightly and the user may see a small number of duplicated or skipped items at the page boundary where the expiry happened. Accepted v1 behavior; visible only when the underlying ranking changes within the TTL window.

The response shape has no `total` — infinite-scroll FE doesn't need it, and dropping it removes a second DB query per request.

### Re-indexing on the v3 canonical-text bump

Canonical-text v3 has a new sectional layout (TYPOLOGY/CHARACTERISTICS/FEATURES/NEARBY/DESCRIPTION/LOCATION/PRICE) aligned with `_render_query_for_embed` on the query side. Every listing's `embedding_text_hash` is invalidated by the version bump, so the next `PROPERTY_UPDATED.v1` event triggers a re-embed automatically. Stagnant listings (no further events) need the existing canonical-text backfill spec mechanism to enqueue a `PROPERTY_LISTING_UPDATED.v1` for each active row. Metadata schema stays at ADR-013 V1 — no parallel-namespace dance needed.

### Read path sources

- ADR: [`docs/adr/014-structured-query-extraction-and-hybrid-retrieval.md`](../adr/014-structured-query-extraction-and-hybrid-retrieval.md)
- Spec: `.claude/specs/active/2026-05-listing-search-structured-extraction.md`
- Use case: `src/listings/application/use_cases/search_listings.py` (rewritten — extract → asyncio.gather → cardinality guard → hydrate → partition-and-rank)
- `/locations` use case: `src/listings/application/use_cases/list_locations.py`
- Route validation helper: `src/listings/adapters/api/search_validation.py`
- `QueryExtractor` port: `src/listings/application/ports/query_extractor.py`
- LLM adapter: `src/listings/adapters/ai/langchain_query_extractor.py`
- Identity adapter (tests + flag-off): `src/listings/adapters/inmemory/inmemory_query_extractor.py`
- `ParsedQuery` value object: `src/listings/domain/parsed_query.py`
- `PoiCategory` closed enum: `src/listings/domain/poi_category.py` (contract-tested against `properties.domain.models.property_poi.PoiCategory`)
- `LocationFilter` value object: `src/listings/domain/location_filter.py`
- `list_ids_for_search` on the repository: `src/listings/application/ports/repositories/property_listing_repository.py`
- Static location catalog: `src/listings/static_data/locations.json`
- Integration test: `tests/integration/test_search_endpoint.py`
