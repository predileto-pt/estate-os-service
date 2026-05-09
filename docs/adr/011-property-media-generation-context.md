# ADR-011: Property media generation — AI image & video workflow as a new bounded context

**Date:** 2026-05-07
**Status:** Proposed (v1 — keep simple, iterate before implementation)

## Context

The admin dashboard wants a new capability: an agent picks an existing property image, types a prompt, and the system produces either (a) a refined / re-imagined image or (b) a short marketing video derived from that source image. The agent then attaches the result to the listing they're preparing.

Today every external-call pipeline in the repo is owned by an existing context: `properties` owns OCR/extraction, `screening` owns applicant document AI, `contract_intelligence` owns contract LLM analysis, `listings` owns POI / cost-of-living enrichment (ADR-010). None of those is a natural home for this new flow. Three observations make it a new context rather than a feature inside `properties`:

1. **It is generative, not extractive.** Every existing pipeline takes a real document/image and produces structured facts about it. This pipeline takes a source image and *creates a new asset*. The lifecycle is different — it has its own state machine (`pending → processing → completed | failed`), its own retry semantics, its own per-generation cost ledger.
2. **It owns its own data, money, and audit trail.** Product wants per-generation cost in tokens and EUR, per-user and per-organization usage rollups, and the full prompt history (raw and LLM-enhanced) kept for review. That's a billable-feature ledger, not a column on `property_images`. Putting it inside `properties` would tangle the property aggregate with cost accounting it has no business carrying.
3. **It pulls in two new external dependencies, both async and slow.** Runway ML for video (multi-minute job, polling-based), an image-generation model for images (seconds-to-tens-of-seconds), and LangChain + OpenAI for prompt enhancement on every request. None of these belong inside the existing context containers; isolating them in a dedicated context keeps the failure blast radius (rate limits, billing surprises, vendor outages) contained.

The agent flow is also intentionally async end-to-end: the admin dashboard fires-and-forgets, then polls or subscribes for completion. We do not want a 90-second HTTP request blocking a browser tab.

## Decision

### 1. New bounded context: `media_generation`

A new context lives at `src/media_generation/`, mirroring the hex layout used by every other context (`domain/`, `application/`, `adapters/`, `entrypoints/`, `container.py`).

**On the name.** `media_generation` is direct, technology-neutral, and reads the same as `contract_intelligence` — domain language, not a product-marketing label. Alternatives considered and rejected: `creative_studio` (sounds like a UI feature, not a domain), `marketing_media` (too narrow — agents may use the output for things other than marketing), `ai_media` (couples the name to the implementation), `generated_assets` (overloads "asset" with billing/contract usage).

The context container is exposed as `app.state.media_generation_container` and follows the same callable-Protocol cross-context import rules as the others (see `CLAUDE.md` cross-context dependency rules).

### 2. Aggregate: `GeneratedMedia`

One aggregate root: `GeneratedMedia`. One generation request produces one aggregate. Fields (initial v1):

| Field | Notes |
|---|---|
| `id` | UUID, PK |
| `organization_id` | UUID, scoping for cost rollup + RBAC |
| `requested_by_user_id` | UUID, identity user |
| `media_type` | enum: `IMAGE` \| `VIDEO` |
| `status` | enum: `PENDING` \| `PROCESSING` \| `COMPLETED` \| `FAILED` |
| `source_property_id` | UUID, FK-by-id to `properties.property` |
| `source_listing_property_id` | UUID nullable, FK-by-id to `listings.property_listing` if one exists at request time |
| `source_image_id` | UUID, FK-by-id to `properties.property_image` |
| `raw_prompt` | text, what the agent typed |
| `enhanced_prompt` | text nullable, output of LangChain + GPT enhancement step (null until the enhancement step runs) |
| `output_s3_bucket` | text |
| `output_s3_key` | text nullable, populated when the asset is uploaded |
| `output_content_type` | text nullable (`image/png`, `video/mp4`, …) |
| `output_size_bytes` | bigint nullable |
| `output_duration_seconds` | int nullable, video only |
| `provider` | text — `runway` for video, `openai` (or whatever) for image |
| `model_name` | text — concrete model identifier captured at run time |
| `total_cost_usd` | numeric(10, 4) — sum across enhancement + generation calls |
| `total_tokens_input` | int |
| `total_tokens_output` | int |
| `wall_seconds` | int — total wall-clock from `processing` to `completed`/`failed` |
| `error_code`, `error_message` | text nullable |
| `created_at`, `updated_at`, `completed_at` | timestamptz |

Linking to **both** `property` and `property_listing` lives directly on the row (two FK-by-id columns) rather than a join table. Reason: each generation belongs to exactly one source property and at most one listing; the join-table flexibility would be a hypothetical future requirement we don't have.

### 3. Per-call cost breakdown: `generation_cost_entries`

Sidecar child table. One row per external provider call within a generation:

| Field |
|---|
| `id` |
| `generated_media_id` (FK) |
| `kind` — enum `PROMPT_ENHANCEMENT` \| `IMAGE_GENERATION` \| `VIDEO_GENERATION` |
| `provider`, `model_name` |
| `tokens_input`, `tokens_output` |
| `cost_usd` |
| `duration_seconds` |
| `created_at` |

The aggregate's `total_*` columns are the rollup of these rows. The breakdown table exists so that finance / product can answer "what did the prompt-enhancement step cost us this month vs. the generation step" without re-deriving it from logs. We accept the small write-amplification (2–3 rows per generation) as the price of an auditable cost ledger.

### 4. Async pipeline & events

The flow is end-to-end asynchronous. The HTTP request only validates input, persists a `PENDING` aggregate, and publishes a command. A worker does the actual work.

**Command (point-to-point, dedicated SQS queue, single consumer):**

- `MEDIA_GENERATION_REQUESTED.v1` — payload `{ generation_id }`. The handler reloads the aggregate from the DB; we deliberately do not put the prompt or source image into the message body (keeps SQS payloads small, makes redelivery idempotent against the DB).

**Domain events (broadcast via SNS, ADR-008 fan-out):**

- `MEDIA_GENERATION_COMPLETED.v1` — payload `{ generation_id, organization_id, source_property_id, source_listing_property_id, media_type, s3_bucket, s3_key }`. Subscribers we already foresee: a future notifications handler ("your generation is ready"), and potentially a listings-side cache-warming handler if we ever embed generated media into the listing search.
- `MEDIA_GENERATION_FAILED.v1` — payload `{ generation_id, organization_id, error_code }`. Same fan-out shape; lets ops/notifications listen without reading the DB.

The split between command (request) and event (completion) follows the pattern already established by ADR-008: requests are point-to-point work tickets, completions are broadcast facts.

### 5. Worker pipeline stages

Single handler, single SQS queue (`media-generation-events-queue`), wrapped by the shared `SQSWorker`. On each `MEDIA_GENERATION_REQUESTED.v1` message:

1. **Load + transition.** Load aggregate by id, assert it's `PENDING`, transition to `PROCESSING`. (Idempotency: if it's already `PROCESSING`/`COMPLETED`/`FAILED`, ack and return — duplicate delivery.)
2. **Resolve source.** Look up `PropertyImage` via a `SourceImageReader` port (callable Protocol implemented by `properties` context, returns an S3 URI + presigned read URL). Locate the listing by `source_property_id` via a `ListingLookup` port (returns `property_listing_id` if any, else None) — populates `source_listing_property_id` on the row if it wasn't supplied at request time.
3. **Enhance prompt.** Call a `PromptEnhancer` port (LangChain + GPT adapter) with `(raw_prompt, media_type, image_metadata)`. Persist `enhanced_prompt` and append a `generation_cost_entries` row with `kind=PROMPT_ENHANCEMENT`.
4. **Generate.** Branch on `media_type`:
   - `IMAGE`: call an `ImageGenerator` port (OpenAI image-generation adapter) with `(source_image_url, enhanced_prompt)` → returns bytes.
   - `VIDEO`: call a `VideoGenerator` port (Runway ML adapter) with `(source_image_url, enhanced_prompt, duration_seconds)`. Runway is poll-based — the adapter encapsulates submit-then-poll-until-done, with heartbeat-driven `extend_visibility` calls on the SQS message (per ADR-008 §`Message.extend_visibility`) so a multi-minute Runway job doesn't trip redelivery. Returns bytes.
   - Append a `generation_cost_entries` row with `kind=IMAGE_GENERATION` or `VIDEO_GENERATION`.
5. **Upload.** Write bytes to the new S3 bucket via a `MediaStorage` port. Key shape `org/{organization_id}/property/{property_id}/{generation_id}.{ext}`.
6. **Finalize.** Update aggregate: `status=COMPLETED`, `output_*` columns, `total_*` cost rollups, `wall_seconds`, `completed_at`. Publish `MEDIA_GENERATION_COMPLETED.v1`. Ack.
7. **On any failure** at steps 2–5: persist `status=FAILED`, `error_code`, `error_message`, partial cost entries (we already paid for them — record them), publish `MEDIA_GENERATION_FAILED.v1`. **Re-raise** so SQS redrive policy decides retry-vs-DLQ (ADR-008 per-handler DLQ). Idempotency at step 1 prevents double-work on retry.

### 6. Storage: new S3 bucket

`MEDIA_GENERATION_S3_BUCKET=estate-os-generated-media` (or env-overridable). Distinct from existing buckets (`estate-os-property-images`, screening document buckets) because:

- **Different lifecycle.** Generated media is regeneratable from prompts; we may want a shorter retention / lower storage class than authoritative source images.
- **Different access pattern.** These will be served to admins (private, presigned) initially, possibly to public listings later — but always derivative of a source we already store. Keeping it separate makes a future "purge all generated media for org X" trivial.
- **Different blast radius.** A misconfigured policy on the generated-media bucket cannot leak source property images.

### 7. API surface (admin)

All routes mounted under `/api/v1/admin/`, behind `require_org_member`:

| Route | Use case |
|---|---|
| `POST /admin/properties/{property_id}/media-generations` | `RequestMediaGeneration` — body `{ source_image_id, media_type, prompt, options? }`. Returns 202 with `{ generation_id, status: "PENDING" }`. Validates source image belongs to the property and the org owns the property, persists the row, publishes the command. |
| `GET /admin/properties/{property_id}/media-generations` | `ListPropertyMediaGenerations` — paginated history for that property. |
| `GET /admin/media-generations/{id}` | `GetMediaGeneration` — single record + presigned download URL if `COMPLETED`. Used by the dashboard to poll status. |
| `GET /admin/organizations/{organization_id}/media-generations` | `ListOrgMediaGenerations` — org-wide history with cost summaries (used for the "usage this month" dashboard view). |

Every route returns the cost rollup on the row. The breakdown table is queryable internally only in v1 (no public route until product asks for it).

### 8. Cross-context dependencies

`media_generation` consumes two callable Protocols from other contexts (same pattern as `organizations` consuming identity's `RegisterUserPort`):

- `SourceImageReader` — implemented by `properties.container`, returns `(s3_uri, presigned_read_url, content_type, image_metadata)` for a given `(property_id, image_id)`. Lives in `properties.application.ports`. Wired at app startup into `media_generation_container`.
- `ListingLookup` — implemented by `listings.container`, returns `Optional[listing_property_id]` for a given `property_id`. Lives in `listings.application.ports`.

Inverse direction (other contexts depending on `media_generation`) is not in scope for v1. If we ever surface generated media on the public listing page, we'll add a callable Protocol the listings context calls — not the other way around.

### 9. Configuration (env vars)

```bash
# Storage
MEDIA_GENERATION_S3_BUCKET=estate-os-generated-media
MEDIA_GENERATION_PRESIGNED_URL_TTL_SECONDS=3600

# Prompt enhancement (LangChain + OpenAI)
MEDIA_GENERATION_PROMPT_MODEL=gpt-...           # configurable; product picks the model
MEDIA_GENERATION_PROMPT_MAX_OUTPUT_TOKENS=400
OPENAI_API_KEY=...                              # already exists

# Image generation
MEDIA_GENERATION_IMAGE_MODEL=gpt-image-1        # placeholder; real model TBD
MEDIA_GENERATION_IMAGE_DEFAULT_SIZE=1024x1024

# Video generation (Runway)
RUNWAY_API_KEY=...
RUNWAY_API_BASE_URL=https://api.dev.runwayml.com
MEDIA_GENERATION_VIDEO_DEFAULT_DURATION_SECONDS=5
MEDIA_GENERATION_VIDEO_POLL_INTERVAL_SECONDS=10
MEDIA_GENERATION_VIDEO_MAX_WAIT_SECONDS=600

# Cost units — used to convert provider responses into EUR/USD
MEDIA_GENERATION_COST_CURRENCY=USD
```

### 10. Quotas (deferred but flagged)

Generative media is genuinely expensive — orders of magnitude more than any LLM call we make today. The cost ledger above is the *measurement* foundation. The *enforcement* (per-org monthly budgets, hard caps, throttling) is a follow-up that lives in `billing` — `media_generation` will eventually call a `QuotaCheck` port from billing before publishing the command, and reject the request synchronously if the org is over quota. Out of scope for v1; the column shapes above are designed so we can add it without a schema change.

## Consequences

- **New bounded context** with its own container, schema, alembic migrations, worker, and SQS queue. Per the architecture rubric, this is the same template as adding any other context — no new abstractions.
- **Two new SNS topics** (`MEDIA_GENERATION_COMPLETED.v1`, `MEDIA_GENERATION_FAILED.v1`) and one new SQS command queue (`media-generation-commands`) plus one work queue (`media-generation-events-queue`) with its DLQ. Provisioned via `scripts/localstack-init.sh` for local + IaC for prod.
- **One new S3 bucket** with its own lifecycle policy.
- **Two new cross-context callable Protocols** (`SourceImageReader` from properties, `ListingLookup` from listings). Implementing them is a few lines in each container — no domain coupling.
- **Three new outbound adapter classes**: Runway video adapter, image-generation adapter, LangChain prompt-enhancement adapter. Each is testable in isolation against the corresponding port.
- **Cost ledger becomes load-bearing for product.** Once we expose "usage this month" in the dashboard, the breakdown table's correctness is a customer-visible property — every new provider call site MUST append a row.
- **Long-running worker jobs.** Runway video can take minutes. The `Message.extend_visibility` heartbeat pattern (already specified by ADR-008) is mandatory here, not optional. Implementation must use it.
- **Operational surface widens.** Two new external dependencies (Runway, image-generation API) join the on-call surface. Each needs a health/quota dashboard before this ships.

## Alternatives considered

1. **Add `GeneratedMedia` as a sibling of `PropertyImage` inside `properties`.** Rejected: tangles cost accounting with the property aggregate, couples external API outages to the property hot path, and conflates "asset that *is* the property" with "asset *derived from* the property."
2. **Synchronous HTTP-blocking generation.** Rejected: video takes minutes and image takes tens of seconds. Browsers and load balancers will time out long before the providers do.
3. **Single combined event `MEDIA_GENERATION_COMPLETED.v1` with a `success: bool` flag instead of separate completed/failed events.** Rejected: violates the one-event-one-meaning convention from ADR-008. Subscribers that only care about successes shouldn't have to filter.
4. **Reuse the existing property images S3 bucket.** Rejected: different lifecycle, different blast radius for IAM mistakes, and harder to purge a single org's generated media without touching authoritative sources.
5. **Synchronous prompt enhancement at HTTP time, async generation only.** Rejected: that splits the cost ledger across the request path and the worker path, and double-charges latency on the agent's POST. Cleaner to do all of it in the worker.
6. **Skip the prompt-enhancement step in v1.** Tempting, but rejected: the prompt enhancement is the difference between "agent types four words and gets a generic image" and "agent types four words and gets something usable." Without it the feature won't be adopted, and adding it later means re-baselining costs.
7. **Store cost per provider call inline as JSON on the aggregate.** Rejected: makes "sum cost by `kind` across the org this month" a JSON-column aggregate query instead of a relational one. The breakdown table is one extra `INSERT` per call and pays for itself the first time finance asks.

## Out of scope

- **Concrete model selection** for prompt enhancement and image generation. Picked at implementation time, recorded on every aggregate row.
- **Public-facing exposure of generated media** on the property search portal. v1 is admin-only.
- **Editing / variants / chaining** (re-generate from a previous generation as the new source). v1 is one-shot.
- **Per-org quota enforcement.** Measured in v1, enforced in a follow-up.
- **Webhook ingestion from Runway.** v1 is poll-based inside the worker; if Runway's webhook story lands first we revisit.
- **Backfill / replay of historical prompts.** No history exists yet — nothing to backfill.
- **Multilingual prompt enhancement.** Agents type in PT/EN today; we'll observe and decide.
- **Cost reconciliation** against the actual Runway / OpenAI invoice. The numbers we record are the providers' returned per-call estimates; finance reconciliation is a separate problem.

## Iteration plan

This ADR is intentionally light. We iterate by adding:

- v2: concrete domain models (`GeneratedMedia`, `GenerationCostEntry`), enum definitions, exception hierarchy.
- v3: schema migration + worker pipeline pseudocode (state transitions, error mapping, exact heartbeat cadence).
- v4: provider-adapter contracts (Runway request/response shapes, OpenAI image API shape, LangChain chain definition) and failure-mode detail.
- v5: quota enforcement integration with billing.

Each iteration appends a section here and bumps the status. Once status flips to **Accepted**, we open the implementation spec under `.claude/specs/active/`.
