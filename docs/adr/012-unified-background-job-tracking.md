# ADR-012: Unified background-job tracking for cross-context async workflows

**Date:** 2026-05-09
**Status:** Proposed (v2 — sharpened from review; ready to break into an implementation spec)

## Context

The service has accumulated several long-running, asynchronous workflows, each owned by a different bounded context. Today they share a *shape* but no *abstraction*:

| Context | Workflow | State today |
|---|---|---|
| `properties` | Document extraction (single + batch) | `ExtractionJob` aggregate + `extraction_jobs` table — full lifecycle (PENDING → PROCESSING → COMPLETED \| FAILED \| RETRYING), per-job error message, result `property_id` |
| `properties` | POI auto-discovery enrichment (ADR-010, slice 2) | None — fire-and-forget command, no record of "is this still running, did it fail, what categories were touched" |
| `screening` | Applicant document screening | Per-applicant status fields on the applicant aggregate; no standalone job rows |
| `contract_intelligence` | Contract ingestion + analysis | State scattered across the contract aggregate; no unified "is this still working" surface |
| `media_generation` (ADR-011, proposed) | AI image / video generation | `GeneratedMedia` aggregate carries its own status; ADR-011 already inlines a state machine |

Each context independently invents a status enum, a "list jobs for org" query, an error-message column, and a UI integration. The dashboard cannot answer two questions that are now becoming product-critical:

1. **"What is currently running for this property?"** — A property may simultaneously have a document-extraction job, a POI enrichment, an in-flight image generation, and (later) an applicant-screening dependency. Today the UI has to query four endpoints and stitch them together.
2. **"What is currently running for this organization?"** — An admin opening their dashboard wants a single feed of "in-flight work and recent failures across everything," not a per-context drill-down.

**Why now.** ADR-011 (`media_generation`) is in flight and will inline its own state machine on `GeneratedMedia` if we don't establish the abstraction first. Every async workflow added between now and then is one more retrofit. The cheapest moment to generalize is *before* ADR-011 ships, not after.

This ADR is about that generalization: a **single read-model + lightweight write port** that any context can use to register, update, and report on background work, without coupling the producing contexts to one another.

## Decision

### 1. Placement: shared infrastructure, not a bounded context

`jobs` lives at `src/shared/jobs/`, parallel to `src/shared/events/`. Per `CLAUDE.md`: "Shared infrastructure (`src/shared/`) — middleware, events, database engine, config — may call any bounded context's container directly. It's not a bounded context itself." `jobs` fits this exactly — it has no domain logic of its own, it's a tracking surface.

The cross-context Protocol examples cited in the original draft (`RegisterUserPort`, `SeedFreemiumSubscription`) are *domain* operations one context delegates to another's business logic. `JobTracker` is generic CRUD — same shape regardless of which context calls it. That's the **events bus pattern** (`EventPublisher`, `CommandPublisher` ports in `src/shared/events/ports.py`), not the user-registration pattern.

```
src/shared/jobs/
├── domain/
│   └── job.py                    # Job, JobKind, JobEntityType, JobStatus, exceptions
├── application/
│   ├── ports/
│   │   ├── job_tracker.py        # Write Protocol — start/complete/fail
│   │   └── repositories/
│   │       └── job_repository.py # Persistence Protocol
│   └── use_cases/
│       ├── start_job.py
│       ├── complete_job.py
│       ├── fail_job.py
│       ├── list_jobs.py
│       └── get_job.py
├── adapters/
│   ├── persistence/
│   │   ├── supabase_job_repository.py
│   │   └── inmemory_job_repository.py     # test double
│   └── api/
│       └── routes/
│           └── jobs.py                    # GET /admin/jobs, GET /admin/jobs/{id}
└── container.py                           # exposed as app.state.jobs
```

There is no `entrypoints/` or worker — `jobs` does no async work itself.

### 2. Aggregate: `Job`

One aggregate root per piece of tracked work. Fields (v1):

| Field | Notes |
|---|---|
| `id` | UUID, PK |
| `organization_id` | UUID, scoping for RBAC and "my org's jobs" feed |
| `requested_by_user_id` | UUID, **NOT NULL** in v1 (no system-initiated jobs exist yet — widen to nullable when one does) |
| `kind` | enum, see §3 — polymorphic discriminator |
| `status` | enum: `PENDING` \| `PROCESSING` \| `COMPLETED` \| `FAILED` |
| `entity_type` | enum: `PROPERTY` \| `LISTING` \| `APPLICANT` \| `CONTRACT` \| `GENERATED_MEDIA` (extensible) — what this job is *operating on* |
| `entity_id` | UUID. **FK-by-id**: a UUID with no SQL FK constraint, since `jobs` is shared infra and cannot reference tables in other contexts. Pair `(entity_type, entity_id)` is the common UI filter. |
| `title` | text — human-readable label rendered in the UI ("Extract documents from upload `acme-3.pdf`", "Discover POIs near Avenida Liberdade 12"). See §11 for i18n. |
| `error_code` | text nullable — short machine-readable code (e.g. `provider_unavailable`, `validation_failed`) for UI grouping |
| `error_message` | text nullable — human-readable failure summary |
| `result_summary` | JSONB nullable, **soft-capped at 4KB**, per-kind schema discipline (§10). Small structured payload the UI renders on completion (e.g. `{"created_property_id": "..."}`, `{"pois_discovered": 14, "had_failures": false}`). |
| `started_at` | timestamptz nullable — set on `PENDING → PROCESSING` |
| `completed_at` | timestamptz nullable — set on `PROCESSING → COMPLETED \| FAILED` |
| `created_at`, `updated_at` | timestamptz |

Indexes:

- `(organization_id, status, created_at DESC)` — org-wide running/recent feed
- `(entity_type, entity_id, kind, created_at DESC)` — "jobs for this property of this kind" (the per-entity recovery query, §6)
- `(kind, status, created_at DESC)` — ops queries ("how many enrichments failed today")

The aggregate deliberately does **not** carry the workflow's domain payload (no `document_keys`, no `prompt`, no `pois_discovered_per_category`). The producing context keeps that in its own tables. `jobs` is a *thin tracking surface*, not a competing source of truth.

`progress_pct` is **deferred** — none of the v1 workflows can produce it meaningfully (extraction is atomic from Reducto's POV; enrichment uses HTTP-fanout per §9 and surfaces only the parent's status; media generation is atomic from Runway's POV until it ships a webhook progress signal). Re-introduce when one workflow commits to producing it.

### 3. `JobKind` enum — polymorphic discriminator

```python
class JobKind(str, enum.Enum):
    PROPERTY_DOCUMENT_EXTRACTION = "property_document_extraction"
    PROPERTY_ENRICHMENT = "property_enrichment"
    APPLICANT_SCREENING = "applicant_screening"
    CONTRACT_INGESTION = "contract_ingestion"
    CONTRACT_ANALYSIS = "contract_analysis"
    MEDIA_GENERATION_IMAGE = "media_generation_image"
    MEDIA_GENERATION_VIDEO = "media_generation_video"
```

New kinds are added by appending. `kind` is the primary filter the UI uses when rendering category-specific badges or icons.

### 4. Status state machine

```
              +-----------+
              |  PENDING  |
              +-----+-----+
                    |
                    | worker picks up
                    v
              +------------+
              | PROCESSING |
              +-+--------+-+
       success  |        |  failure
                v        v
        +-----------+  +--------+
        | COMPLETED |  | FAILED |
        +-----------+  +--------+
```

- **No `RETRYING`** in v1 (unlike `ExtractionJob` today). A retry produces a *new* `Job` row pointing at the same `(entity_type, entity_id)`. The mapping is **1:N** — one logical workflow can have many `Job` rows over its retry history. `parent_job_id` to link them is deferred to v2.
- **No `CANCELLED`** in v1. Cooperative cancellation is a separate ADR.
- Transitions are enforced in the domain model (raise `InvalidJobTransitionError` on illegal moves), mirroring the existing `ExtractionJob.mark_processing()` pattern.

### 5. Write port: `JobTracker` (Protocol)

Producing contexts depend on a `JobTracker` Protocol injected at container construction — same wiring story as `EventPublisher` / `CommandPublisher` (`src/shared/events/ports.py`). The `bootstrap.py` constructs the concrete adapter from the shared `JobRepository`, then passes the Protocol-shaped instance into every context's container.

```python
# src/shared/jobs/application/ports/job_tracker.py
from typing import Protocol
from uuid import UUID

class JobTracker(Protocol):
    async def start(
        self,
        *,
        organization_id: UUID,
        requested_by_user_id: UUID,
        kind: JobKind,
        entity_type: JobEntityType,
        entity_id: UUID,
        title: str,
    ) -> UUID:
        """Insert a new row in PROCESSING and return its job_id.

        Returns immediately, no PENDING-then-PROCESSING split (§4).
        """
        ...

    async def complete(self, job_id: UUID, result_summary: dict | None = None) -> None:
        """Idempotent on COMPLETED. Raises if current status is FAILED."""
        ...

    async def fail(self, job_id: UUID, error_code: str, error_message: str) -> None:
        """Idempotent on FAILED. Raises if current status is COMPLETED."""
        ...
```

**Three methods, not five.** `mark_processing` is folded into `start` (§4 — `start` creates the row directly in PROCESSING; the `PENDING` state is reserved for workflows that need to distinguish queue-time from execution-time, none of which exist in v1). `update_progress` is dropped along with `progress_pct` (§2).

**Idempotency contract:**
- `complete(job_id)` after `complete(job_id)` with the same args → no-op.
- `fail(job_id)` after `fail(job_id)` with the same args → no-op.
- `complete(job_id)` after `fail(job_id)` (or vice versa) → raises `InvalidJobTransitionError`. Workflows that race here have a deeper bug.

The producing context keeps a `tracked_job_id: UUID` on its own aggregate (or in its command-message body) so the worker can call `complete` / `fail` from inside the worker handler.

### 6. Read API: split between shared and per-context routes

| Route | Lives in | Use case |
|---|---|---|
| `GET /admin/jobs` | `src/shared/jobs/adapters/api/routes/jobs.py` | `ListJobs` — query params: `status` (comma-separated for `pending,processing`), `kind`, `entity_type`, `entity_id`, `limit`, `cursor`. Org is always inferred from `require_org_member`. |
| `GET /admin/jobs/{id}` | `src/shared/jobs/adapters/api/routes/jobs.py` | `GetJob` — single record. The UI polls this for in-flight jobs in v1; SSE/websockets deferred. |
| `GET /admin/properties/{id}/jobs` | `src/properties/adapters/api/routes/properties.py` | Calls `request.app.state.jobs.list_jobs.execute(entity_type=PROPERTY, entity_id=...)`. Same model for `/applicants/{id}/jobs`, `/contracts/{id}/jobs`. The producing context owns the URL because it owns the entity; shared infra owns the data. |

**Per-entity recovery flow.** When the user navigates back to a property page, the frontend calls:

```
GET /admin/properties/{id}/jobs?kind=property_enrichment&limit=5
```

and applies its own active-vs-terminal logic on the response (sorted `created_at DESC`):

- If any returned job is in `pending` or `processing`, render the live-progress UI and poll `GET /admin/jobs/{id}`.
- Else, if there's a recent terminal job, render its `result_summary` (last completion time / last failure card).
- Else, render the empty state ("no enrichment yet").

`localStorage` is **not** the recovery mechanism — the listing endpoint is. The action endpoints (`POST /admin/properties/{id}/enrich`, `POST /admin/properties/{id}/extract`, etc.) return `{ job_id, status: "processing" }` in the 202 body so the frontend has the id for the immediate session, but on reload it's recomputed from the listing.

### 7. Cross-context wiring

In `shared.entrypoints.bootstrap`:

```python
job_repo = SupabaseJobRepository(client)
jobs_container = SharedJobsContainer(job_repo=job_repo)
app.state.jobs = jobs_container

# Producing contexts inject JobTracker via constructor
app.state.property_container = PropertyContainer(
    ...
    job_tracker=jobs_container.job_tracker,   # Protocol-typed
)
```

`shared/jobs` does **not** import from any producing context. The `entity_id` / `entity_type` columns are FK-by-id only. (See §2.)

Producing contexts call `JobTracker.start()` from inside their HTTP-triggering use case (e.g. `EnqueueEnrichProperty`), put the returned `job_id` into the SQS command payload, and the worker handler calls `complete` / `fail` after the work resolves.

### 8. Migration strategy for existing `ExtractionJob`

`ExtractionJob` (and its `extraction_jobs` table) **stays put.** It carries properties-specific domain state (`document_keys`, `listing_type`, `typology`, `property_id`) that doesn't belong on the generic `background_jobs` row.

The integration is one-way:

1. `SubmitPropertyExtraction` writes a new `ExtractionJob` row, then calls `JobTracker.start(kind=PROPERTY_DOCUMENT_EXTRACTION, entity_type=PROPERTY, entity_id=...)`. The returned `tracked_job_id` is stored on the `ExtractionJob` row (new nullable column added in the migration).
2. `ProcessPropertyExtraction` worker calls `JobTracker.complete(tracked_job_id, result_summary={"created_property_id": ...})` on success or `JobTracker.fail(tracked_job_id, ...)` on failure, alongside its existing `ExtractionJob.mark_*` calls.
3. The existing `GET /admin/extraction-jobs/{id}` endpoint stays — old clients that need the rich extraction-specific payload still hit it. New UI work uses the unified `GET /admin/jobs/...` feed.

**Retry mapping is 1:N.** `ExtractionJob.RETRYING` stays internal to the properties context — it's a state of the *extraction* aggregate. Each retry attempt corresponds to a *new* `Job` row with the same `(entity_type=PROPERTY, entity_id=X, kind=PROPERTY_DOCUMENT_EXTRACTION)`. The unified surface gets a clean immutable timeline; the rich extraction state lives where it has always lived. Reading "the latest job for this property's extraction" is `ORDER BY created_at DESC LIMIT 1` on the listing endpoint.

### 9. Fanout boundary: HTTP-fanout only in v1

All v1 workflows use **HTTP-fanout**: one SQS message → one worker invocation → that worker performs N parallel HTTP calls internally. Examples:
- POI enrichment: 1 message → worker → 18 concurrent Google Places HTTP calls.
- Document extraction: 1 message → worker → Reducto + LLM HTTP calls.

From the job perspective: one parent `Job`, no children. The worker calls `start` on entry and `complete` / `fail` once, when all internal HTTP work resolves.

**SQS-fanout** (one trigger → N independent SQS messages → N independent worker invocations) is **not supported in v1**. Adding it requires `parent_job_id` on `Job`, a parent-status computation rule (PROCESSING while any child is non-terminal; COMPLETED when all done; FAILED if any failed), and a sidecar children table. All deferred to v2 and only added when a workflow genuinely needs it (e.g. media generation parallelizing video renders across workers).

This invariant matters because it bounds the v1 implementation: the worker handler can call `JobTracker.complete` synchronously at the end of its own async function. No distributed-state computation, no eventual-consistency timing on the parent status.

### 10. `result_summary` schema discipline

Per-kind shape, owned by the producing context. Each producing context's worker is responsible for emitting a payload that conforms to its kind's documented schema. Examples (illustrative — finalized in v3 implementation spec):

| Kind | `result_summary` shape |
|---|---|
| `PROPERTY_DOCUMENT_EXTRACTION` | `{"created_property_id": UUID}` on success; absent on failure |
| `PROPERTY_ENRICHMENT` | `{"pois_discovered": int, "categories_processed": int, "had_failures": bool}` |
| `MEDIA_GENERATION_IMAGE` | `{"output_s3_key": str, "total_cost_usd": float, "model_name": str}` |
| `MEDIA_GENERATION_VIDEO` | `{"output_s3_key": str, "duration_seconds": int, "total_cost_usd": float}` |

**Soft cap of 4KB** enforced at the `JobTracker.complete` adapter layer — payloads larger than that are rejected with a logged warning and stored truncated. The cap exists to stop a future contributor from dumping a full extraction result in there. If a workflow legitimately needs a larger result body, that's a sidecar table in the producing context, not a wider `result_summary`.

The `entity_id` already lets the UI fetch the rich domain row (e.g. the created property) — `result_summary` is a *display optimization*, not the source of truth.

### 11. Authorization

- All read routes are behind `require_org_member`. Members of an org see all jobs for that org regardless of who initiated them. Per-user filtering is a UI concern, not a backend authz concern.
- The `JobTracker` write port is **trusted** — it's only called from inside producing-context workflows, which have already authorized the originating action. `start()` does not re-verify that `requested_by_user_id` is a member of `organization_id`; the producing context vouches for the inputs.
- Admin (Predileto staff) cross-org visibility is **out of scope** in v1 — would require a new route bypassing `require_org_member`. Deferred.

### 12. ADR-011 sequencing

ADR-012 ships **before** ADR-011 implementation begins. Concretely:

- ADR-011 is currently `Proposed (v1)`. Its implementation spec has not been opened.
- This ADR (012) reaches `Accepted` and its v3 implementation spec ships first.
- ADR-011's eventual implementation spec references the `JobTracker` port directly: `media_generation`'s worker calls `JobTracker.start / complete / fail` alongside its own `GeneratedMedia.status` transitions. The aggregate's status field stays as the source of truth for the aggregate; the unified row is the cross-context view.

If ADR-011 implementation starts first for an unrelated reason (product priority, blocking dependency), the retrofit is four added lines in the worker — no schema change to `media_generations`. But the planned ordering is 012-then-011.

### 13. Configuration

No new env vars. The shared `jobs` infra is purely Postgres-backed. Reuses the existing Supabase client and credentials.

If we later add push-based UI updates (SSE), that's a v5 concern with its own envs.

## Consequences

- **One new shared infrastructure module** (`src/shared/jobs/`), one new table (`background_jobs`), one new read API. Same template as `src/shared/events/`. No new abstractions invented.
- **One new Protocol** (`JobTracker`). Every producing context grows one constructor arg and a handful of `start` / `complete` / `fail` calls inside its existing workflows.
- **Two-table redundancy for extraction jobs.** `extraction_jobs` (rich domain state) and `background_jobs` (thin tracking) coexist. Accepted as the price of decoupling — collapsing them would force `background_jobs` to carry per-context columns and defeat the purpose. The `tracked_job_id` linkage column makes joins cheap when needed.
- **Eventual-consistency window between the producing-context write and the `JobTracker` write.** The producing contexts use the Supabase HTTP client, which writes one row per HTTP call — there is no client-side multi-table transaction available. Both writes happen sequentially in the same async function. A crash between them is observable as either a `Job` in `PROCESSING` whose extraction-side work never started, or a completed extraction with no `Job` row. Mitigation: an **orphan reaper** marks `PROCESSING` rows older than `T` (e.g. 30 min) as `FAILED` with `error_code=tracker_orphaned`. The reaper is in v3's implementation spec, not deferred — it's the *only* mitigation we have given the persistence model.
- **No SQL FK** between `(entity_type, entity_id)` and the producing context's table. If a property is hard-deleted, its job rows linger. Acceptable: jobs is an audit trail; deletions of source aggregates shouldn't erase the operational history.
- **UI polling cost.** `GET /admin/jobs?status=pending,processing` becomes a hot endpoint when the dashboard is open. The `(organization_id, status, created_at DESC)` index serves it. Quantified target for v3: p99 < 200ms at 1000 in-flight jobs per org with 50 concurrent dashboard users polling at 3s. Revisit when we cross that.
- **Operational legibility goes up.** Single feed of in-flight work + failures becomes the primary place ops looks when "things feel slow" — replacing today's "grep four context logs."
- **Per-context test doubles.** An `InMemoryJobTracker` ships in `src/shared/jobs/adapters/inmemory/` and is used by every producing context's tests, matching the existing in-memory adapter pattern.

## Alternatives considered

1. **Bounded context (`src/jobs/`) with cross-context callable Protocols.** Rejected in §1 — `jobs` has no domain logic, fits the shared-infra rubric. Treating it as a context would import `RegisterUserPort` semantics where they don't belong.
2. **Shared `background_jobs` table written by every context directly (no Protocol).** Rejected: every context would need to import `shared/jobs/adapters/persistence`, coupling them at the persistence layer instead of through a Protocol. The Protocol indirection costs nothing and lets us swap the adapter in tests.
3. **Same DB transaction for producing-context write + `JobTracker` write.** Considered, then ruled out: producing contexts use the Supabase HTTP client (one HTTP call per write) — there's no multi-table transaction available client-side. Adopting this would mean rewriting every context's persistence layer to use direct PG connections. The orphan reaper (Consequences) is the real mitigation.
4. **Event-driven projection.** Producing contexts emit `JOB_STARTED.v1` / `JOB_COMPLETED.v1` / `JOB_FAILED.v1` on the existing SNS bus (ADR-008); shared `jobs` subscribes and projects. Cleaner separation, but: (a) introduces eventual-consistency gap on the *write* path the dashboard polls, (b) doubles the moving parts (every workflow grows an event publisher AND a tracker), (c) needs a replay tool for projection rebuilds. Deferred — if we ever need cross-service tracking, we revisit. For a single-service v1 the synchronous Protocol is simpler and just as decoupled.
5. **Keep per-context job tables, build a database VIEW that UNIONs them.** Rejected: columns don't line up, every new context forces the view to grow, and `kind` / `entity_type` filters degrade into `CASE` expressions. Maintenance burden grows quadratically.
6. **Don't track POI enrichment / media generation as jobs at all — only show extraction.** Rejected: the dashboard story without it is incomplete; this is the whole reason the ADR exists.
7. **Make `jobs` a saga / process-manager that owns the work.** Workflows submitted to `jobs`, which dispatches. Rejected: massively heavier abstraction, requires a routing layer, and inverts the ownership model where each context owns its own commands/queues. A nice destination if we ever centralize orchestration; not the right starting point.
8. **Reuse the existing `ExtractionJob` aggregate, rename + generalize it.** Rejected: keeps it inside `properties`, where other contexts shouldn't import from. Cleaner to leave `ExtractionJob` where it is and add a thin tracking sibling.
9. **`status` as a wider enum** (`QUEUED`, `RETRYING`, `CANCELLING`, `CANCELLED`, `TIMED_OUT`). Rejected for v1: each extra state is one the producing context has to drive correctly *and* the UI has to render. Four states cover the questions the dashboard actually asks today; we add more when we have a concrete need.
10. **`entity_type` as text instead of enum.** Considered. Enum chosen for v1 because it surfaces typos at migration time and gives the read API a closed set to validate against. Each new producing context adds a value via migration — accepted cost given how rarely we add producing contexts.

## Out of scope

- **Push-based progress updates** (SSE / websockets). v1 is poll-based.
- **Per-job cost tracking.** ADR-011 has its own `generation_cost_entries` table for media-generation cost. Generalizing cost rollups across job kinds is a follow-up; lives in a sibling table, not on `Job`.
- **Cooperative cancellation** (`POST /admin/jobs/{id}/cancel`). v1 has no cancel button; no `CANCELLED` state.
- **Retry chaining** (`parent_job_id`). v2 — only matters once we surface "this is the third retry" in the UI.
- **SQS-fanout workflows.** v1 supports HTTP-fanout only (§9). SQS-fanout requires `parent_job_id` + a sidecar children table + parent-status computation — deferred to v2 alongside retry chaining.
- **Cross-organization admin views** (Predileto staff seeing *all* orgs' jobs). v1 is org-scoped only.
- **Dashboard widget contracts.** UI design (badges, polling cadence, what counts as "active") is out of scope for the backend ADR; the contract is the API shape above.
- **Metrics/observability surface** (Prometheus / Logfire dashboards over `background_jobs`). Useful, deferred to a follow-up.
- **Migration of `screening` and `contract_intelligence` job-like state into the unified surface.** First implementation ships with `properties` (extraction + enrichment) and `media_generation` (ADR-011) as the integrators. Other contexts opt in over time.
- **`progress_pct`.** Re-introduce when one workflow commits to producing it (§2).

## Open questions

To be resolved before v3 (implementation spec) is opened:

1. **i18n for `title`.** The Portolar monorepo is multilingual (PT / EN / DE / FR / ES per the root `CLAUDE.md`). Producing contexts generate `title` strings. Options: (a) store `title` in PT only and let the frontend translate via a key map, (b) store `title_key` + `title_args` JSON and let the frontend localize, (c) store `title` in the user's locale at the moment of `start()`. Decision needed; my lean is (b) — it's the only option that handles late-rendering correctly when an admin changes locale.
2. **Reaper cadence and threshold.** The orphan reaper is committed (Consequences); the parameters aren't. Probably "older than 30 min in PROCESSING" run every 5 min, but should be confirmed against the longest legitimate workflow runtime (Runway video — multi-minute, per ADR-011 §5).
3. **Per-kind authorization.** v1 says "any org member sees any org job." Are there job kinds (e.g. financial, contract-related) where only specific roles should see them? Punted to product; if yes, add a `visibility_role` column to `Job` in a future iteration.
4. **`error_code` taxonomy.** The column exists; the closed set of values doesn't. v3 should ship with a per-kind error code map (e.g. `provider_unavailable`, `validation_failed`, `quota_exceeded`, `tracker_orphaned`) so the UI can group consistently across kinds.
5. **Pagination contract.** Cursor-based vs offset-based for `GET /admin/jobs`. Cursor scales better; offset is simpler. v3 picks one.

## Iteration plan

This ADR is intentionally light. We iterate by adding:

- **v3:** concrete domain models, exception hierarchy, full state-transition rules, schema migration (table + indexes), `tracked_job_id` column on `extraction_jobs`, integration spec for the two initial workflows (`SubmitPropertyExtraction`, `EnqueueEnrichProperty`), per-kind `result_summary` schemas, orphan-reaper cron, resolution of all five Open Questions.
- **v4:** retry chaining (`parent_job_id`), SQS-fanout support (parent-status computation, sidecar children table pattern), cooperative cancellation if needed.
- **v5:** push-based progress updates (SSE first; websockets only if SSE proves insufficient), `progress_pct` reintroduction once a workflow commits to producing it.

Each iteration appends a section here and bumps the status. Once status flips to **Accepted**, we open the implementation spec under `.claude/specs/active/`.
