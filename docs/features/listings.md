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

Filter active properties by listing type, typology, district (substring on address), price range, with offset pagination. Used by the public property search.

- **Inputs:** `PropertyFilters` dataclass
  - `listing_type?` — `SALE` / `PURCHASE`
  - `typology?` — `HOUSE` / `APARTMENT` / `LAND` / `RUIN`
  - `min_price?`, `max_price?` — `Decimal`
  - `district?` — substring match on address
  - `limit` (1-100, default 20)
  - `offset` (default 0)
- **Output:** `(list[ListedProperty], int)` — items and total count
- **Side effects:** none. The route handler enriches images with pre-signed URLs.
- **Notes:** price filtering is applied post-query because prices are stored in a separate table.
- **Source:** `src/listings/application/use_cases/list_properties.py`

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

Worker uses the shared `SQSWorker` (ADR-008) with heartbeat-extended visibility so long LLM calls on enrichment don't trip visibility-timeout redelivery.

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

### Rollout flag

The pipeline is gated by `LISTINGS_EMBEDDING_ENABLED` (default `false`). When off, the embedding handler is a no-op — messages are still consumed (no DLQ buildup) but no embed/upsert work runs and `embedding_status` stays `PENDING`. Bootstrap doesn't even construct the OpenAI/Pinecone adapters in this mode, so a missing `PINECONE_API_KEY` won't crash the worker.

To enable in staging:

```bash
export LISTINGS_EMBEDDING_ENABLED=true
export PINECONE_API_KEY=...
export PINECONE_INDEX=listings-staging
export VECTOR_INDEX_NAMESPACE=openai-text-embedding-3-small-v1
uv run python -m listings.entrypoints.events_worker
```

Production flips after staging is clean. A separate spec ships the backfill CLI under `src/listings/entrypoints/backfill_embeddings.py` for pre-existing rows.

### Environment variables

| Variable                        | Description                                                                                                                  | Default                                       |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| `LISTINGS_EMBEDDING_ENABLED`    | Master gate. When `false`, embedding handler is a no-op.                                                                     | `false`                                       |
| `EMBEDDING_MODEL`               | OpenAI embedding model. Used as `embedding_model_version` on the row.                                                        | `text-embedding-3-small`                      |
| `EMBEDDING_DIMENSIONS`          | Vector dimensions. Must match the model.                                                                                     | `1536`                                        |
| `VECTOR_INDEX_PROVIDER`         | Backing store selector. Today only `pinecone` is wired in production; the in-memory adapter ships for tests + local dev.    | `pinecone`                                    |
| `VECTOR_INDEX_NAMESPACE`        | Pinecone namespace = embedding model version. A model bump means: build a new namespace, validate, atomically flip this var. | `openai-text-embedding-3-small-v1`            |
| `PINECONE_API_KEY`              | Pinecone API key (required when `LISTINGS_EMBEDDING_ENABLED=true`).                                                          | —                                             |
| `PINECONE_INDEX`                | Pinecone index name (host or alias).                                                                                         | `listings-prod`                               |
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
