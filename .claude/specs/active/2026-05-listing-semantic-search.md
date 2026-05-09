# Listing semantic search — indexing pipeline (ADR-013 phase 1)

**Status:** in-progress
**Owner:** Peter
**Created:** 2026-05-09

## Problem

ADR-013 (Accepted, v2) pins the architecture for free-text semantic search over published listings — Pinecone behind a `VectorIndex` port, listings-owned `PROPERTY_LISTING_UPDATED.v1` domain event triggering the embedding handler, POIs flowing through the upstream property snapshot. Today the listings context has only the projector handler and a structured-filter `GET /api/v1/listings/properties` — no embedding, no vector index, no canonical-text composition.

This spec lands **phase 1: the indexing pipeline (write path)** — everything needed for the index to stay live as `PROPERTY_*.v1` events flow, populated and ready before any search traffic. The read path (LocationExtractor, QueryRewriter, two-stage search) ships in a follow-up spec.

## Goal

Every published `property_listings` row is embedded into the Pinecone index, kept in sync as `PROPERTY_*.v1` events arrive, and observable via `embedding_status` for ops. No public-facing endpoint changes in this phase.

## Non-goals

- **Read path** (search use case, `LocationExtractor`, `QueryRewriter`, `q=` query parameter on `GET /api/v1/listings/properties`) — follow-up spec.
- POI structured-data payload shape on `PROPERTY_*.v1` events (properties-context responsibility; this spec consumes whatever shape lands).
- POI-write batching inside the properties auto-discovery workflow (properties-context responsibility; precondition in ADR-013 §2a).
- Backfill of existing `property_listings` rows — separate spec for the one-shot CLI under `src/listings/entrypoints/backfill_embeddings.py`.
- Pinecone index provisioning, region/tier sizing — infra spec.
- Cross-encoder re-ranker, personalized search, faceted counts, multilingual embeddings — out of scope per ADR.

## Approach

### Overview

```
PROPERTY_PUBLISHED.v1 / PROPERTY_UPDATED.v1 / PROPERTY_DELETED.v1
        │
        ▼
listings worker  ──►  handle_property_event (existing projector)
                          ├─ upsert property_listings (incl. new pois jsonb column)
                          └─ publish PROPERTY_LISTING_UPDATED.v1 to SNS  (NEW)
                                                  │
                                                  ▼
                                       handle_listing_embedding (NEW handler)
                                       ├─ compose canonical text from row + POIs
                                       ├─ hash check (skip if unchanged)
                                       ├─ EmbeddingProvider.embed
                                       ├─ VectorIndex.upsert
                                       └─ update embedding_* columns + status
```

ADR-013 §2b specifies in-process dispatch for `PROPERTY_LISTING_UPDATED.v1`. **This spec deviates** to match the existing `NEEDS_ADDRESS_ENRICHMENT` SNS pattern (see `src/listings/adapters/workers/property_event_handler.py:78-87`); a follow-up commit amends ADR-013 §2b to reflect the SNS choice with the rationale (precedent, per-handler DLQ, failure isolation).

### 1. Properties-side: POI in event snapshot

`src/properties/application/events/property_event.py` — `build_property_snapshot()` adds a `pois` field. Each POI serialized as a lean dict:

```python
{"category": "school", "name": "Escola X", "distance_meters": 234.0}
```

Source data: `PropertyPoiRepository.list_by_property(property_id)` called inside `build_property_snapshot()` (the function gets a repository handle injected; mirror how the address is read today). POIs are filtered to category-allowlist + non-null name + distance ≤ `POI_SNAPSHOT_MAX_DISTANCE_M` (default 5000m) before serialization. Capped at `POI_SNAPSHOT_MAX_COUNT` (default 30) sorted by distance ascending.

This is the only change in the properties context — surgical, motivated by ADR-013 §2a precondition.

### 2. Listings-side: schema migration

Two migrations (committed sequentially):

**Migration A** (`20260509_160000_fc1250e0b892_add_listings_embedding_columns.py`) adds the embedding-pipeline columns and POIs to `property_listings`:

| Column | Type | Default | Notes |
|---|---|---|---|
| `embedding_text_hash` | text | NULL | SHA-256 hex |
| `canonical_text_version` | text | NULL | e.g. `v1` |
| `embedding_model_version` | text | NULL | e.g. `text-embedding-3-small` |
| `embedded_at` | timestamptz | NULL | last successful upsert |
| `embedding_status` | text | `'PENDING'` | CHECK constraint: `PENDING` / `INDEXED` / `FAILED` |
| `pois` | jsonb | `'[]'::jsonb` | list of `{category, name, distance_meters}` |

Plus a partial b-tree index on `embedding_status WHERE embedding_status != 'INDEXED'` for the ops dashboard query.

**Migration B** (added during canonical-text composer work) extends the projection with two characteristic columns the composer needs but the projector wasn't carrying:

| Column | Type | Default | Notes |
|---|---|---|---|
| `built_at` | integer | NULL | year built (carried from `characteristics.built_at`) |
| `energy_rating` | text | NULL | energy class string (carried from `characteristics.energy_rating`) |

Both columns are projected from the same `characteristics` dict the snapshot already carries — the projector mapping just adds two more `chars.get(...)` reads. No properties-side change.

### 3. Listings-side: canonical-text composer

`src/listings/application/services/canonical_text.py` (NEW) — pure function `compose_canonical_text(row: PropertyListingRow) -> CanonicalText` returning `(text: str, version: str, hash: str)`.

Renders per `LISTING_CANONICAL_TEXT_V1` schema in ADR-013 §3a. POI rendering format (locked here):

```
NEARBY: school: Escola X (0.2km), school: Externato Y (0.5km), supermarket: Pingo Doce (0.4km), ...
```

- Sort key: `(category.value, distance_m_rounded, name.lower())` — total order, deterministic
- Distance rounded to nearest 100m; rendered as `<n.n>km` (one decimal, e.g. `0.2km`, `1.4km`)
- Hard cap at `LISTING_POI_MAX_COUNT=20` (env-configurable per ADR §3a)
- Filter-before-render: POIs with category outside the allowlist or `distance_meters > LISTING_POI_MAX_DISTANCE_M` (default 3000m) dropped

Hash: `hashlib.sha256(text.encode("utf-8")).hexdigest()`.

### 4. Listings-side: ports + adapters

New ports under `src/listings/application/ports/`:

- `embedding_provider.py` — `EmbeddingProvider(Protocol)` with `async embed(text: str) -> list[float]`.
- `vector_index.py` — `VectorIndex(Protocol)` with `upsert / delete / update_metadata / query` per ADR §6. Plus value types `VectorMatch`, `VectorFilter` in `src/listings/domain/models/vector.py`.

Adapters:

- `src/listings/adapters/embedding/openai_provider.py` — wraps `openai.AsyncClient.embeddings.create(model=…, input=text)`. Reads `OPENAI_API_KEY`, `EMBEDDING_MODEL` (default `text-embedding-3-small`).
- `src/listings/adapters/vector/pinecone_index.py` — wraps `pinecone-client` async API. Reads `PINECONE_API_KEY`, `PINECONE_INDEX`, `VECTOR_INDEX_NAMESPACE`. Translates `VectorFilter` to Pinecone Mongo-style filter.
- `src/listings/adapters/vector/inmemory_index.py` — Python dict + brute-force cosine; passes the same contract tests as the Pinecone adapter (per ADR §6).

### 5. Listings-side: embedding handler + new domain event

`src/shared/events/types.py` — add `PROPERTY_LISTING_UPDATED_V1 = "PROPERTY_LISTING_UPDATED.v1"`.

`src/listings/adapters/workers/property_event_handler.py` — after `applied=True`, in addition to the existing `NEEDS_ADDRESS_ENRICHMENT` publish, publish `PROPERTY_LISTING_UPDATED.v1` with `{"property_id": data["id"]}`. (Note: `property_id` matches the existing pattern. The embedding handler reads the row by `property_id` from the listings repo.)

`src/listings/adapters/workers/embedding_handler.py` (NEW) — `async handle_listing_embedding(event, context)`:

```
1. Load property_listings row by property_id; if missing, log + return.
2. If embedding gate disabled (LISTINGS_EMBEDDING_ENABLED=false) → return.
3. Compose canonical text. New tuple: (hash, canonical_text_version, embedding_model_version).
4. If new tuple == persisted tuple → metadata path only (status update if changed); return.
5. Set embedding_status=PENDING.
6. Call EmbeddingProvider.embed(text).
7. Call VectorIndex.upsert(vector_id=property_listing_id, vector, metadata, namespace).
8. Update property_listings: hash, canonical_text_version, embedding_model_version, embedded_at, embedding_status=INDEXED.
On any exception: set embedding_status=FAILED, log, re-raise (SQS redrives, terminal → DLQ).
```

`src/listings/entrypoints/events_worker.py` — add subscription `router.on(PROPERTY_LISTING_UPDATED_V1, handle_listing_embedding)`.

### 6. Container + config

`src/listings/container.py` — wire `embedding_provider`, `vector_index`. Both nullable: when `LISTINGS_EMBEDDING_ENABLED=false` they're not constructed and the handler is a no-op. Local dev defaults to in-memory `VectorIndex` and a stub `EmbeddingProvider` (returns deterministic vectors per text hash) so `docker compose up` works without API keys.

Env vars added (per ADR §7):

```
LISTINGS_EMBEDDING_ENABLED=false   # default off in v1
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536
VECTOR_INDEX_PROVIDER=pinecone
VECTOR_INDEX_NAMESPACE=openai-text-embedding-3-small-v1
VECTOR_INDEX_TOP_K=50           # used by read path; defined here for completeness
VECTOR_INDEX_REQUEST_TIMEOUT_SECONDS=5
PINECONE_API_KEY=
PINECONE_INDEX=listings-prod
LISTING_POI_MAX_COUNT=20
LISTING_POI_MAX_DISTANCE_M=3000
POI_SNAPSHOT_MAX_COUNT=30          # properties-side, for build_property_snapshot
POI_SNAPSHOT_MAX_DISTANCE_M=5000
```

### 7. Test strategy

- **Unit tests** — `tests/unit/listings/services/test_canonical_text.py`: fixed inputs → fixed outputs (golden tests for each field combination, null cases, POI ordering determinism, hash stability across re-runs).
- **Unit tests** — `tests/unit/listings/workers/test_embedding_handler.py`: in-memory `VectorIndex` + stub `EmbeddingProvider`. Cover all branches (hash unchanged → no-op, hash changed → embed+upsert, FAILED status on exception, gate disabled → no-op).
- **Contract tests** — `tests/integration/listings/test_vector_index_contract.py`: parametrize over `[InMemoryVectorIndex, PineconeVectorIndex]` (Pinecone skipped if `PINECONE_API_KEY` unset) — same assertions for both.
- **End-to-end** — `tests/integration/listings/test_indexing_pipeline.py`: emit a `PROPERTY_PUBLISHED.v1` SNS message, assert `property_listings.embedding_status == 'INDEXED'` and a vector exists in the in-memory index with the expected metadata.

### 8. Rollout

1. Migration ships first (additive, no behavior change).
2. Properties-side `build_property_snapshot()` change ships next (POIs in snapshot — backwards-compat: handlers that don't read `pois` are unaffected).
3. Embedding handler ships with `LISTINGS_EMBEDDING_ENABLED=false`. CI/staging flip the flag, observe `embedding_status` transitions, error rates, p95.
4. Production flips the flag once staging is clean.
5. (Out of scope, separate spec) Backfill CLI populates the index for pre-existing listings.

## Affected files / surfaces

- `src/properties/application/events/property_event.py` — add `pois` to `build_property_snapshot()`. Inject `PropertyPoiRepository`; serialize `[{category, name, distance_meters}]`.
- `src/properties/application/use_cases/publish_property.py` (and other emit sites) — pass the POI repo through to `build_property_snapshot()`.
- `src/listings/adapters/database/property_listing_model.py` — add 6 columns (5 embedding + 1 pois).
- `alembic/versions/<new>.py` — migration adding columns + partial index on `embedding_status`.
- New: `src/listings/application/services/canonical_text.py` — pure composer.
- New: `src/listings/application/ports/embedding_provider.py`
- New: `src/listings/application/ports/vector_index.py`
- New: `src/listings/domain/models/vector.py` — `VectorMatch`, `VectorFilter` value types.
- New: `src/listings/adapters/embedding/openai_provider.py`
- New: `src/listings/adapters/vector/pinecone_index.py`
- New: `src/listings/adapters/vector/inmemory_index.py`
- New: `src/listings/adapters/workers/embedding_handler.py`
- `src/listings/adapters/workers/property_event_handler.py` — publish `PROPERTY_LISTING_UPDATED.v1` after applied upsert.
- `src/listings/entrypoints/events_worker.py` — subscribe `handle_listing_embedding` to the new event.
- `src/listings/container.py` — wire `embedding_provider`, `vector_index`.
- `src/shared/events/types.py` — add `PROPERTY_LISTING_UPDATED_V1` constant.
- `src/listings/application/ports/repositories/property_listing_repository.py` — add `set_embedding_status`, `set_embedding_indexed(hash, version, model, embedded_at)` methods.
- `src/listings/adapters/persistence/supabase_property_listing_repo.py` — implement the new methods.
- Tests: `tests/unit/listings/services/test_canonical_text.py`, `tests/unit/listings/workers/test_embedding_handler.py`, `tests/integration/listings/test_vector_index_contract.py`, `tests/integration/listings/test_indexing_pipeline.py`.
- Docs: amend ADR-013 §2b to reflect SNS-based dispatch (separate commit at end of this spec).
- Docs: update `src/listings/CLAUDE.md` (if present) with the embedding pipeline overview.

## Acceptance criteria

- [x] Properties: `build_property_snapshot()` carries `pois` (lean shape); existing tests still green.
- [ ] Migration runs forward and backward cleanly on a populated DB. **(Manual smoke before merge — additive columns only, no data migration; risk low.)**
- [x] `compose_canonical_text` is a pure function with golden tests covering: full property, missing description, missing built year, missing POIs, max-POI cap, deterministic ordering across permuted inputs.
- [x] Hash stability: same row → same hash byte-for-byte across 100 invocations.
- [x] `VectorIndex` contract test passes for `InMemoryVectorIndex` (15 tests). **Pinecone parametrization deferred** — adapter is small (filter translation only) and depends entirely on the SDK behaving as advertised; staging deploy + manual smoke covers it. Captured as a follow-up.
- [x] Embedding handler end-to-end: `test_first_index_embeds_and_upserts` exercises projector-row → embedding handler → vector in the in-memory index with the expected metadata.
- [x] Hash-skip path: `test_hash_unchanged_skips_embed_calls_metadata_path` confirms second identical invocation skips the embed call.
- [x] Gate off: `test_gate_disabled_is_noop` — handler short-circuits when ports are None.
- [x] Failure path: `test_failure_path_marks_row_failed_and_reraises` — embed raises → status=FAILED, exception re-raised so SQS redrives. `test_failed_status_forces_reembed_on_redrive` covers the recovery path.
- [x] `ruff check` clean, `pytest -v` green (399 unit tests).
- [x] ADR-013 §2b amended (v3 status bump) reflecting the SNS-based dispatch.

## Open questions (resolved)

- **POI repository injection in `build_property_snapshot()`** → **Resolved: option (b).** Caller pre-fetches POIs from `PropertyPoiRepository.list_by_property()` and passes them as a parameter. Keeps `build_property_snapshot()` pure / sync. Callers (publish/update use cases) already do DB IO so this is a small additional read.
- **Pinecone async client surface** → **Resolved: pin `pinecone>=5.0` and use `PineconeAsyncio` client** (the dedicated async surface in v5+). Adapter wraps it behind the `VectorIndex` port; no other module sees the client.
- **Embedding model version string format** → **Resolved: use the `EMBEDDING_MODEL` env value verbatim** as `embedding_model_version` (e.g. `text-embedding-3-small`). Drops the `openai:` prefix from the ADR sketch — OpenAI is the only provider for now and the prefix is noise. If we add Voyage/Cohere later we can prefix at that time.

## Out of scope follow-ups

- **Read path** — search use case, `LocationExtractor`, `QueryRewriter`, `q=` query param. Separate spec (phase 2).
- **Backfill CLI** — `src/listings/entrypoints/backfill_embeddings.py` to embed pre-existing rows. Separate spec.
- **Re-embed after address enrichment.** The address-enrichment handler runs *after* the projector and writes `parish/municipality/district` directly. The embedding handler runs in parallel via SNS, so the first embedding lacks the LOCATION line. The address handler should publish `PROPERTY_LISTING_UPDATED.v1` after a successful `update_location` so the embedding handler re-runs with location populated. **Captured here, not solved in this spec.**
- **`handle_address_enrichment` LLM-call de-dup.** Today it re-parses on every event, even if address unchanged. Wasteful; separate concern.
- **Pinecone contract test parametrization.** Run the `test_inmemory_vector_index.py` contract suite against a real Pinecone test namespace, gated on `PINECONE_API_KEY`. Needs a Pinecone test project + a CI secret. Currently the adapter is verified by manual smoke + the SDK's own tests.
- **Properties POI auto-discovery → `PROPERTY_UPDATED.v1`.** The `EnrichProperty` use case writes POIs but doesn't currently publish a `PROPERTY_UPDATED.v1` carrying them. Until it does, only `PublishProperty` seeds POIs onto the listings row; subsequent POI discoveries don't propagate. Properties-context concern, ADR-013 §2a precondition.
- **POI batching guarantee** — integration test in properties asserting the auto-discovery workflow fires exactly one `PROPERTY_UPDATED.v1` per workflow run, not one per discovered POI.
- **Pinecone index provisioning + region/tier sizing** — infra spec.
- **`bool(listings_embedding_enabled)` env parsing.** pydantic-settings handles `"true"`/`"false"`/`"1"`/`"0"` natively; double-check the operator runbook at staging flip.

## Commits

Conventional commits, scope = `listings`:

- `feat(listings): VectorIndex port + Pinecone v1 adapter`
- `feat(listings): canonical-text composer + LISTING_CANONICAL_TEXT_V1`
- `feat(listings): embedding handler + PROPERTY_LISTING_UPDATED.v1 domain event`
- `feat(listings): two-stage search GET /properties?q=<...>`
- `feat(listings): in-memory VectorIndex + LocationExtractor test doubles`
- `chore(listings): alembic migration for embedding_* columns`
