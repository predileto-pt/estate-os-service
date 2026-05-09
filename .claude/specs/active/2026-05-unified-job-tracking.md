# Unified background-job tracking (ADR-012 v3 implementation)

**Status:** draft (sharpened from review)
**Owner:** Peter
**Created:** 2026-05-09

## Problem

ADR-012 §Context lays this out in detail: the dashboard cannot answer "what's running for this property" or "what's running for my org" without stitching together per-context endpoints, because every async workflow today (extraction, enrichment, screening, contract, the upcoming media generation in ADR-011) carries its own status enum and tracking surface. ADR-011 is in flight and will inline another state machine if we don't establish the abstraction first.

## Goal

Ship `src/shared/jobs/` — a shared-infra module exposing a `JobTracker` write Protocol and a `GET /api/v1/admin/jobs` read API — and integrate it into the two existing async workflows (`SubmitPropertyExtraction` and `EnqueueEnrichProperty`). The acceptance bar is **the backend surface the dashboard will consume**; the dashboard UI itself is a separate frontend deliverable.

## Non-goals

- **Push-based UI updates** (SSE / websockets). v1 is poll-based.
- **`progress_pct` field.** None of the v1 workflows produce it.
- **`parent_job_id` / SQS-fanout / retry chaining.** Deferred to v4 of the ADR.
- **`CANCELLED` state / cancellation endpoint.** Deferred.
- **Migration of `screening` and `contract_intelligence` job-like state.** Other contexts opt in over time; first ship is properties + (eventual) ADR-011 only.
- **Cost tracking on Job rows.** ADR-011 has its own `generation_cost_entries` sidecar.
- **Cross-organization admin views.** v1 is org-scoped.
- **i18n on `title`.** PT-only per ADR §11.
- **Pagination cursor.** `?limit=N` only (default 10, max 50), most recent first.

## Approach

Mirrors ADR-012 §1–§13. The implementation map:

### New shared module: `src/shared/jobs/`

```
src/shared/jobs/
├── __init__.py
├── domain/
│   ├── __init__.py
│   ├── job.py                              # Job, JobKind, JobEntityType, JobStatus
│   └── exceptions.py                       # InvalidJobTransitionError, JobNotFoundError
├── application/
│   ├── __init__.py
│   ├── ports/
│   │   ├── __init__.py
│   │   ├── job_tracker.py                  # Protocol (start, complete, fail, update_entity_id)
│   │   └── job_repository.py               # Protocol (insert, update, get_by_id, list)
│   └── use_cases/
│       ├── __init__.py
│       ├── start_job.py
│       ├── complete_job.py
│       ├── fail_job.py
│       ├── list_jobs.py
│       └── get_job.py
├── adapters/
│   ├── __init__.py
│   ├── persistence/
│   │   ├── __init__.py
│   │   ├── supabase_job_repository.py      # AsyncClient → background_jobs table
│   │   └── inmemory_job_repository.py      # test double
│   ├── tracking/
│   │   ├── __init__.py
│   │   └── default_job_tracker.py          # adapter that wraps the four lifecycle operations into the JobTracker Protocol shape
│   └── api/
│       ├── __init__.py
│       └── routes/
│           ├── __init__.py
│           └── jobs.py                     # GET /admin/jobs, GET /admin/jobs/{id}
└── container.py                            # SharedJobsContainer; exposes job_tracker, list_jobs, get_job
```

### Domain

```python
class JobStatus(str, enum.Enum):
    PENDING = "pending"        # reserved; v1 starts in PROCESSING (ADR §5)
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class JobKind(str, enum.Enum):
    PROPERTY_DOCUMENT_EXTRACTION = "property_document_extraction"
    PROPERTY_ENRICHMENT = "property_enrichment"
    APPLICANT_SCREENING = "applicant_screening"
    CONTRACT_INGESTION = "contract_ingestion"
    CONTRACT_ANALYSIS = "contract_analysis"
    MEDIA_GENERATION_IMAGE = "media_generation_image"
    MEDIA_GENERATION_VIDEO = "media_generation_video"

class JobEntityType(str, enum.Enum):
    PROPERTY = "property"
    LISTING = "listing"
    APPLICANT = "applicant"
    CONTRACT = "contract"
    GENERATED_MEDIA = "generated_media"
```

`Job` dataclass mirrors ADR §2 fields. State transitions enforce ADR §4: `complete` / `fail` are idempotent on terminal of same kind; cross-terminal transitions raise `InvalidJobTransitionError`.

### Write port

`JobTracker(Protocol)` with four methods:

- `start(*, organization_id, requested_by_user_id, kind, entity_type, entity_id, title) -> UUID` — inserts a row in `PROCESSING` (no `PENDING` in v1, ADR §5), returns the new `job_id`.
- `complete(job_id, result_summary=None) -> None` — idempotent on `COMPLETED`; raises `InvalidJobTransitionError` if currently `FAILED`.
- `fail(job_id, error_code, error_message) -> None` — idempotent on `FAILED`; raises if currently `COMPLETED`.
- `update_entity_id(job_id, entity_id) -> None` — repoints a non-terminal row at a different entity. Used by extraction (see §Producing-context integration) where the row is created with `entity_id=extraction_job.id` and re-pointed to the new property's id once the worker creates the property. Raises if the row is already terminal.

`DefaultJobTracker` adapter (in `src/shared/jobs/adapters/tracking/default_job_tracker.py`) wraps the four lifecycle operations into the `JobTracker` Protocol shape.

### Read API

Both routes require `?organization_id=X` as a query param so they can use the standard `require_org_member` dependency, identical to every other admin route in the codebase.

- `GET /api/v1/admin/jobs?organization_id=X&status=&kind=&entity_type=&entity_id=&limit=`
  - `status` accepts a comma-separated list of values (e.g. `pending,processing`).
  - `limit` defaults to 10, validated as `Query(ge=1, le=50)` — out-of-range returns 422.
  - Sorted `created_at DESC`.
  - Returns `list[JobResponse]`.
- `GET /api/v1/admin/jobs/{id}?organization_id=X`
  - Returns `JobResponse`.
  - Loads the row, then **404** (not 403) if `job.organization_id != organization_id` — same shape as "not found" so we don't leak existence across orgs.

`JobResponse` (Pydantic) mirrors the `Job` aggregate fields: `id`, `organization_id`, `requested_by_user_id`, `kind`, `status`, `entity_type`, `entity_id`, `title`, `error_code`, `error_message`, `result_summary`, `started_at`, `completed_at`, `created_at`, `updated_at`. Lives in `src/shared/jobs/adapters/api/schemas.py`.

### Per-context convenience routes (this PR ships only the properties one)

- `GET /api/v1/admin/properties/{property_id}/jobs?organization_id=X&kind=&limit=` — calls shared `app.state.jobs_container.list_jobs.execute(entity_type=PROPERTY, entity_id=property_id, organization_id=organization_id, kind=..., limit=...)`. Lives in `src/properties/adapters/api/routes/properties.py`. Behind `require_org_member` like every other admin route.

### Schema

New table `background_jobs`:

| col | type | notes |
|---|---|---|
| `id` | uuid PK | server default `gen_random_uuid()` |
| `organization_id` | uuid | FK to `organizations.id` ON DELETE CASCADE |
| `requested_by_user_id` | uuid | FK to `users.id` (NOT NULL in v1) |
| `kind` | enum `job_kind` | |
| `status` | enum `job_status` | default `processing` |
| `entity_type` | enum `job_entity_type` | |
| `entity_id` | uuid | NOT NULL, **no SQL FK** (FK-by-id) |
| `title` | text | NOT NULL, pt-PT |
| `error_code` | text | nullable |
| `error_message` | text | nullable |
| `result_summary` | jsonb | nullable, soft-cap 4KB enforced in adapter |
| `started_at` | timestamptz | NOT NULL, server default `now()` (v1 starts in PROCESSING) |
| `completed_at` | timestamptz | nullable |
| `created_at`, `updated_at` | timestamptz | server defaults + `update_updated_at_column` trigger |

Indexes (ADR §2):
- `(organization_id, status, created_at DESC)`
- `(entity_type, entity_id, kind, created_at DESC)`
- `(kind, status, created_at DESC)`

RLS service-role policy + trigger like every other table.

`extraction_jobs` gains a nullable `tracked_job_id uuid` column (no FK constraint — `background_jobs` is shared infra).

### Bootstrap wiring

```python
# src/shared/entrypoints/bootstrap.py

_jobs_container: SharedJobsContainer | None = None

async def get_jobs_container() -> SharedJobsContainer:
    global _jobs_container
    if _jobs_container is not None:
        return _jobs_container
    settings = Settings()
    client = await acreate_client(settings.supabase_url, settings.supabase_service_role_key)
    _jobs_container = SharedJobsContainer(job_repo=SupabaseJobRepository(client))
    return _jobs_container


# Inside get_property_container(): jobs is built first so its tracker
# can be injected.
jobs = await get_jobs_container()
_property_container = PropertyContainer(
    ...,
    job_tracker=jobs.job_tracker,
)
```

`shared/main.py` lifespan ordering:

```python
app.state.identity_container = await get_identity_container()
app.state.billing_container = await get_billing_container()
app.state.container = await get_container()
app.state.jobs_container = await get_jobs_container()        # NEW — must precede property
app.state.property_container = await get_property_container()
# ...rest unchanged
```

The shared jobs router (`src/shared/jobs/adapters/api/routes/jobs.py`) is mounted under `/api/v1/admin` alongside the other admin routers in `create_app()`.

### Producing-context integration

#### Extraction (no property exists at submission time)

The `entity_type / entity_id` model assumes the entity exists at `start()` time. For extraction this is false: the property is *created* by the worker. We resolve this with **deferred re-pointing**:

1. At submission time, the row is created with `entity_type=PROPERTY, entity_id=extraction_job.id`. Using `extraction_job.id` as a placeholder (rather than introducing a `JobEntityType.EXTRACTION`) keeps the enum closed and lets the row repoint to a real property id post-completion without changing its `entity_type`.
2. After the worker creates the property, it calls `JobTracker.update_entity_id(job_id, property.id)` immediately before `complete()`, so anyone querying "jobs for property X" via `(entity_type=PROPERTY, entity_id=X)` sees the historical extraction job.

**`SubmitPropertyExtraction`** (HTTP request → command publish). Order: **start job → insert ExtractionJob → publish command** (one crash window between start and insert; orphan reaper handles the in-PROCESSING-with-no-extraction case per ADR §Consequences).

1. `tracked_job_id = await job_tracker.start(kind=PROPERTY_DOCUMENT_EXTRACTION, entity_type=PROPERTY, entity_id=extraction_job.id, organization_id=..., requested_by_user_id=..., title=f"Extrair propriedade — {len(document_keys)} documento(s)")`.
2. Insert `ExtractionJob` row with `tracked_job_id` already set (single insert, not insert-then-update).
3. Publish `PROPERTY_EXTRACTION_REQUESTED.v1` (existing).
4. Return both the extraction job and `tracked_job_id` to the route layer.

**`ProcessPropertyExtraction`** (worker). The `ExtractionJob` row already carries `tracked_job_id`; the worker reads it after `extraction_job_repo.get_by_id(...)`.

- On success:
  1. `mark_completed(prop.id)` on the `ExtractionJob` (existing).
  2. `await job_tracker.update_entity_id(tracked_job_id, prop.id)`.
  3. `await job_tracker.complete(tracked_job_id, result_summary={"created_property_id": str(prop.id)})`.
- On failure: `mark_failed(...)` (existing) + `await job_tracker.fail(tracked_job_id, error_code="extraction_failed", error_message=str(exc))`.

#### Enrichment (entity exists at start time)

**`EnqueueEnrichProperty`** (HTTP request → command publish). Order: **validate → start job → publish command** (the SQS publish is the last write, so a crash between start and publish leaves a job in PROCESSING that the reaper cleans).

1. Existing validation: `get_by_id` + coordinate guard.
2. `tracked_job_id = await job_tracker.start(kind=PROPERTY_ENRICHMENT, entity_type=PROPERTY, entity_id=property_id, organization_id=..., requested_by_user_id=..., title=f"Descobrir POIs perto de {prop.address}")`.
3. Publish `ENRICH_PROPERTY_REQUESTED.v1` with payload extended to include `tracked_job_id=str(tracked_job_id)`.
4. Return `tracked_job_id` to the caller.

**`EnrichProperty`** (worker). The handler unpacks `tracked_job_id` from the SQS payload and passes it to `execute()`. **Every** exception path through `execute()` flows through `JobTracker.fail()` before re-raising:

- On success: existing path + `await job_tracker.complete(tracked_job_id, result_summary={"pois_discovered": len(discovered_pois), "categories_processed": len(categories_to_run), "had_failures": any_failures})`.
- On failure: wrap the body of `execute()` in a single `try / except Exception as exc`. The handler classifies and maps:
  - `PropertyNotFoundError` → `error_code="property_not_found"` (the property was deleted between enqueue and pickup).
  - `PropertyMissingCoordinatesError` → `error_code="property_missing_coordinates"`.
  - The provider-down `RuntimeError` from §4 of `enrich_property.py` → `error_code="provider_unavailable"`.
  - Anything else → `error_code="enrich_failed"`.
- After `JobTracker.fail()`, **re-raise** so SQS visibility retry policy applies. `fail()` is idempotent on `FAILED`, so re-deliveries pointing at the same `tracked_job_id` won't conflict.

**Retry idempotency invariant.** If `execute()` succeeds but `complete()` fails (DB unreachable mid-flight), SQS redelivers and the worker re-runs the whole enrichment. `replace_for_property` is destructive (delete-then-insert per `supabase_property_poi_repo.py:81`), so the second run overwrites the first with equivalent data. The cost of retry is one extra Google Places fan-out plus one extra POI catalog rewrite — acceptable. This invariant must hold for any future workflow that calls `complete()` after side-effects.

### Action endpoints return job_id

New Pydantic response models live in `src/properties/adapters/api/schemas.py`.

- `POST /admin/properties/{id}/enrich` → returns `EnrichPropertyResponse(job_id: UUID, status: str = "processing", property_id: UUID)`. The `status` value is `JobStatus.PROCESSING.value` literally, not a free-form string — keeps the action response consistent with the unified job surface.
- `POST /admin/extraction-jobs/` (existing) — the existing response gains a nullable `tracked_job_id: UUID | None` field. Existing fields stay; this is additive.

## Affected files / surfaces

### New files (shared/jobs)

- `src/shared/jobs/__init__.py`
- `src/shared/jobs/domain/__init__.py`
- `src/shared/jobs/domain/job.py`
- `src/shared/jobs/domain/exceptions.py`
- `src/shared/jobs/application/__init__.py`
- `src/shared/jobs/application/ports/__init__.py`
- `src/shared/jobs/application/ports/job_tracker.py`
- `src/shared/jobs/application/ports/job_repository.py`
- `src/shared/jobs/application/use_cases/__init__.py`
- `src/shared/jobs/application/use_cases/start_job.py`
- `src/shared/jobs/application/use_cases/complete_job.py`
- `src/shared/jobs/application/use_cases/fail_job.py`
- `src/shared/jobs/application/use_cases/list_jobs.py`
- `src/shared/jobs/application/use_cases/get_job.py`
- `src/shared/jobs/adapters/__init__.py`
- `src/shared/jobs/adapters/persistence/__init__.py`
- `src/shared/jobs/adapters/persistence/supabase_job_repository.py`
- `src/shared/jobs/adapters/persistence/inmemory_job_repository.py`
- `src/shared/jobs/adapters/tracking/__init__.py`
- `src/shared/jobs/adapters/tracking/default_job_tracker.py`
- `src/shared/jobs/adapters/api/__init__.py`
- `src/shared/jobs/adapters/api/routes/__init__.py`
- `src/shared/jobs/adapters/api/routes/jobs.py`
- `src/shared/jobs/adapters/api/schemas.py`
- `src/shared/jobs/container.py`

### New files (alembic + tests)

- `alembic/versions/<new>_add_background_jobs_table.py`
- `tests/unit/shared/jobs/test_job_domain.py`
- `tests/unit/shared/jobs/test_use_cases.py`
- `tests/unit/shared/jobs/test_inmemory_repo.py`
- `tests/unit/shared/jobs/test_default_tracker.py`
- `tests/e2e/test_jobs_routes.py`
- `tests/e2e/test_property_jobs_route.py`
- `tests/e2e/test_extraction_with_job_tracking.py`
- `tests/e2e/test_enrichment_with_job_tracking.py`

### Updated files

- `src/properties/container.py` — accept `job_tracker: JobTracker | None`; pass into `SubmitPropertyExtraction`, `EnqueueEnrichProperty`, `ProcessPropertyExtraction`, `EnrichProperty`.
- `src/properties/application/use_cases/submit_property_extraction.py` — call `start` *before* the `ExtractionJob` insert; bake `tracked_job_id` into the inserted row; return `(job, tracked_job_id)`.
- `src/properties/application/use_cases/process_property_extraction.py` — on success: `update_entity_id(prop.id)` then `complete()`. On failure: `fail(error_code="extraction_failed")`.
- `src/properties/application/use_cases/enqueue_enrich_property.py` — call `start`; **return `tracked_job_id: UUID`** (currently returns `None`); include `tracked_job_id` in the SQS payload.
- `src/properties/application/use_cases/enrich_property.py` — accept `tracked_job_id` kwarg; wrap `execute()` body in a single try/except that maps known exceptions to `error_code` strings, calls `fail()`, then re-raises. On success, call `complete()` with the `result_summary` shape from §Producing-context integration.
- `src/properties/adapters/workers/enrichment_processor.py` — extract `tracked_job_id` from `event.data["tracked_job_id"]` and pass to `enrich_property.execute()`.
- `src/properties/adapters/api/routes/properties.py` — `enrich_property` route returns `EnrichPropertyResponse`; new `GET /properties/{property_id}/jobs?organization_id=X&kind=&limit=` route that calls `app.state.jobs_container.list_jobs.execute(entity_type=PROPERTY, entity_id=property_id, ...)`.
- `src/properties/adapters/api/routes/extraction_jobs.py` — submission response gains `tracked_job_id` field.
- `src/properties/adapters/api/schemas.py` — add `EnrichPropertyResponse(job_id: UUID, status: str, property_id: UUID)`; add `tracked_job_id: UUID | None` to the existing extraction-submission response model.
- `src/properties/domain/models/extraction_job.py` — add `tracked_job_id: UUID | None = None`.
- `src/properties/adapters/persistence/supabase_extraction_job_repo.py` — read/write the new column.
- `src/properties/adapters/database/models.py` — add `tracked_job_id` column to `ExtractionJobModel`.
- `src/shared/entrypoints/bootstrap.py` — `get_jobs_container()`; injection of `jobs.job_tracker` into `get_property_container()`.
- `src/shared/main.py` — lifespan adds `app.state.jobs_container = await get_jobs_container()` *before* `app.state.property_container`; mount `shared/jobs/adapters/api/routes/jobs.py` router under `/api/v1/admin`.
- `tests/database/test_migration.py` — bump revision id; include `background_jobs` in expected tables; assert new triggers.

## Acceptance criteria

- [ ] `Job` aggregate enforces transitions (`complete` from `FAILED` raises; double-`complete` no-ops; double-`fail` no-ops).
- [ ] `Job.update_entity_id` succeeds while non-terminal; raises `InvalidJobTransitionError` if called after `complete` or `fail`.
- [ ] `SupabaseJobRepository.insert/update/get_by_id/list` round-trip a row and decode all enum fields.
- [ ] `InMemoryJobRepository` passes the same contract tests as the Supabase one (shared fixtures).
- [ ] `DefaultJobTracker.start` creates a row in `PROCESSING` (not `PENDING`) — assert via repo state.
- [ ] `result_summary` payloads larger than 4KB are stored truncated and a structlog warning is emitted.
- [ ] Alembic migration `upgrade()` creates `background_jobs`, three indexes, three enums, RLS service-role policy, `update_updated_at_column` trigger, and adds `tracked_job_id` to `extraction_jobs`. `downgrade()` reverses cleanly.
- [ ] `tests/database/test_migration.py` passes — revision is the new head, `background_jobs` in expected tables, all triggers present.
- [ ] `GET /api/v1/admin/jobs?organization_id=X` returns the most recent 10 jobs for org X, ordered `created_at DESC`.
- [ ] **Cross-org isolation:** `GET /api/v1/admin/jobs?organization_id=X` does NOT return rows belonging to org Y, even when the caller is a member of both. Verified by seeding rows in two orgs and asserting only the requested-org rows appear.
- [ ] `?limit=51`, `?limit=0`, and `?limit=-1` return 422 (Pydantic `Field(ge=1, le=50)`).
- [ ] `GET /api/v1/admin/jobs/{id}?organization_id=X` returns 404 on unknown id, **404 (not 403)** when the row exists but belongs to a different org — the response shape is identical to "not found" so existence is not leaked across orgs.
- [ ] `GET /api/v1/admin/properties/{property_id}/jobs?organization_id=X` returns jobs filtered by `entity_type=PROPERTY, entity_id=property_id`.
- [ ] `POST /api/v1/admin/properties/{id}/enrich` body returns `EnrichPropertyResponse(job_id, status="processing", property_id)`.
- [ ] After `EnqueueEnrichProperty.execute()`, a `background_jobs` row exists with status `PROCESSING`, kind `PROPERTY_ENRICHMENT`, and the returned `tracked_job_id` matches the row's `id`.
- [ ] After `EnrichProperty` completes successfully, the corresponding `background_jobs` row transitions to `COMPLETED` with `result_summary` containing `pois_discovered`, `categories_processed`, `had_failures`.
- [ ] **Every** failure path through `EnrichProperty.execute()` (`PropertyNotFoundError`, `PropertyMissingCoordinatesError`, provider-down `RuntimeError`, generic `Exception`) transitions the row to `FAILED` with the corresponding `error_code` (`property_not_found` / `property_missing_coordinates` / `provider_unavailable` / `enrich_failed`) before the exception propagates so SQS retries.
- [ ] `SubmitPropertyExtraction` writes `tracked_job_id` on the inserted `ExtractionJob` row in a single insert (start-job runs first; orphan-on-crash flagged in §Producing-context integration).
- [ ] After `ProcessPropertyExtraction` succeeds, the `background_jobs` row's `entity_id` has been updated from the original `extraction_job.id` to the new `property.id` via `update_entity_id`, status is `COMPLETED`, and `result_summary.created_property_id` matches.
- [ ] After `ProcessPropertyExtraction` fails, the `background_jobs` row is `FAILED` with `error_code="extraction_failed"`.
- [ ] All existing tests still pass (`uv run pytest -v`). Ruff clean.
- [ ] No imports from `properties.*` / `screening.*` / `contract_intelligence.*` / etc. in `src/shared/jobs/` (`grep -rn "from properties" src/shared/jobs/` → zero hits).

## Open questions

(None — all five resolved in ADR-012 v3.)

## Out of scope follow-ups

- Orphan reaper cron job (own follow-up — needs scheduler). The migration adds the columns and indexes the reaper will need, but the cron itself isn't wired in this PR.
- Per-kind `error_code` taxonomy enforcement (current PR uses free-form strings; a future PR can add a closed set per kind once we have real failure-mode data).
- Migration of `screening` and `contract_intelligence` workflows into the unified surface.
- Push-based progress (SSE).
- Dashboard widget integration (frontend concern; the contract is the API shape above).

## Commits

Single feature commit when everything's green:

```
feat(jobs): unified background-job tracking (shared/jobs/) + properties integration

- New src/shared/jobs/ shared-infra module exposing JobTracker Protocol +
  ListJobs/GetJob use cases. background_jobs table with three indexes,
  RLS service-role policy, updated_at trigger.
- properties context integrates: SubmitPropertyExtraction +
  EnqueueEnrichProperty call JobTracker.start(); the worker use cases
  call complete()/fail() alongside their existing aggregate transitions.
- New routes: GET /admin/jobs, GET /admin/jobs/{id}, GET /admin/properties/{id}/jobs.
- POST /admin/properties/{id}/enrich now returns {job_id, status,
  property_id} so the frontend can poll for status.
- ExtractionJob gains a nullable tracked_job_id column linking to the
  unified row (1:N retry mapping per ADR-012 §8).

Implements ADR-012 v3.
```
