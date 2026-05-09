# Property POI auto-discovery workflow

**Status:** shipped
**Owner:** Peter
**Created:** 2026-05-09
**Shipped:** 2026-05-09 (534 tests green; 24 new — 18 unit, 6 HTTP integration.)

## Problem

The previous spec (`2026-05-property-pois-manual-entry.md`, shipped) gave agents the ability to hand-curate the POI catalog for any property. That's the canonical store, but populating it by hand for every property doesn't scale. The dashboard already has a "discover" button — today it routes through the legacy `DiscoverPropertyAmenities` use case, which writes per-category summaries into `property_amenities` (a different table, different shape, different lifecycle from POIs). That's the system we're consolidating away from per ADR-010 v4.

This spec is **slice 2 of ADR-010's implementation arc**: the agent-triggered async workflow that discovers POIs from an external provider, ranks them, and persists them into `property_pois`. After this lands, the dashboard can switch its "discover" button from the amenity surface to the POI workflow, the cost-of-life slice can compute over real auto-populated data, and the amenity-removal spec becomes feasible.

## Goal

Agents trigger POI discovery for one property via:

```
POST /api/v1/admin/properties/{property_id}/enrich?organization_id=<uuid>
```

The endpoint returns 202 immediately. A new SQS command `ENRICH_PROPERTY_REQUESTED.v1` is published to a dedicated queue. A new worker (`properties.entrypoints.worker --queue enrichment`) consumes it, runs **stage 1** (discover POIs per category via the existing `PlacesService` port → Google Places adapter) and **stage 2** (rank with the just-extracted `proximity_ranker`), and persists the top-N per category into `property_pois`. Manually-edited categories are skipped by default (preserving agent corrections); `force=true` in the request body bypasses the guard.

After this spec ships:
- The dashboard's "discover" button can stop hitting `/api/v1/admin/property-amenities/discover` and start hitting `/properties/{id}/enrich`.
- The cost-of-life slice (next spec) reads from a real, automatically-populated `property_pois` catalog instead of having to manually seed.
- The amenity-removal spec (last) becomes safe — nothing else points at the legacy surface.

## Non-goals

- **Stage 3 (cost-of-life calculation).** Lives in `2026-05-property-cost-of-life.md`. This spec writes raw POIs; it doesn't compute scores.
- **Stage 4 (semantic embedding).** Deferred per ADR §iteration plan v8.
- **Multi-provider `PlacesService`.** Slice ships with the existing `GooglePlacesService` only. `OverpassPlacesService` and the provider-selection factory are a follow-up slice. POIs from this slice are tagged in their `metadata` with `{"provider": "google"}` so the future multi-provider switch can identify rows that need re-discovery if a tenant changes provider.
- **Configurable-settings infrastructure** (`_AppConstants`, DB-backed runtime config, TTL refresh). Categories, radius, and concurrency live as Python constants in this slice. The configurable-settings spec is its own follow-up — it has no other consumer until cost-of-life lands.
- **Geo-cache decorator.** Same reasoning — optimization, separate slice.
- **Per-category freshness tracking.** The existing `property_pois.created_at` is good enough as a "when was this row written" signal for ops queries; we don't add a `discovered_at` column or a category-level freshness state machine. Retry re-calls all non-manually-edited categories. Acceptable cost; the actual API spend is bounded by the agent's clicks.
- **Bulk trigger.** Per ADR v4: no `enrich-batch` endpoint. Agent triggers per-property.
- **Auto-trigger on publish.** Per ADR v4: manual command only. The `AUTO_ENRICH_ON_PUBLISH` flag was deliberately dropped.
- **Removing the legacy amenity surface.** That's its own spec, after the dashboard frontend is migrated.

## Approach

### 1. Command type + transport

New domain command `ENRICH_PROPERTY_REQUESTED.v1` with payload:

```json
{
  "property_id": "<uuid>",
  "organization_id": "<uuid>",
  "force": false,
  "requested_by_user_id": "<domain User.id uuid>"
}
```

`requested_by_user_id` is the domain `User.id` (UUID) — not the `supabase_user_id` string. The domain id is the audit-friendly identifier that matches the `User` aggregate; the supabase id is auth-layer plumbing. Both are accessible from `request.state.user`; we use the domain one.

Published via the existing `SQSCommandPublisher` (ADR-008 — same publisher every other context uses). Lands on a new dedicated queue `property-enrichment-queue` with DLQ `property-enrichment-dlq` and `maxReceiveCount=5`. Provisioning:

- `scripts/localstack-init.sh` — add the queue + DLQ + redrive policy alongside the existing `property-extraction-queue` setup. Same shape, just new names.
- `Settings` class (`src/shared/config.py`) — add `sqs_property_enrichment_queue_url: str = ""` + `sqs_property_enrichment_dlq_url: str = ""`.
- `.env.example` — document the new env var (production wiring is whatever provisions the rest of the SQS surface; this spec only handles local dev + the env var.)

### 2. Admin endpoint

Add to the existing `src/properties/adapters/api/routes/properties.py` next to `publish_property` and `update_property_address`:

```python
@router.post(
    "/{property_id}/enrich",
    status_code=202,
    summary="Trigger POI auto-discovery for a property",
    responses={
        202: {"description": "Enrichment command queued"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not a member of this organization"},
        404: {"description": "Property not found"},
        422: {"description": "Property is missing coordinates"},
    },
)
async def enrich_property(
    property_id: UUID,
    organization_id: UUID,
    body: EnrichPropertyRequest,
    request: Request,
    member: tuple[User, Membership] = Depends(require_org_member),
):
    user, _membership = member
    use_case = request.app.state.property_container.enqueue_enrich_property
    try:
        await use_case.execute(
            property_id=property_id,
            organization_id=organization_id,
            force=body.force,
            requested_by_user_id=user.id,
        )
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")
    except PropertyMissingCoordinatesError:
        raise HTTPException(status_code=422, detail="Property missing coordinates")
    return {"status": "enrichment_queued", "property_id": str(property_id)}
```

The endpoint dispatches to a new use case `EnqueueEnrichProperty` that:
1. Loads the property, verifies cross-org access, raises `PropertyNotFoundError` on miss.
2. Verifies coordinates are set (raises `PropertyMissingCoordinatesError` — same exception the legacy amenity flow already uses).
3. Publishes `ENRICH_PROPERTY_REQUESTED.v1` via the command publisher.

This is the **enqueue** half. The actual workflow runs in the worker.

The body schema is minimal:

```python
class EnrichPropertyRequest(BaseModel):
    force: bool = False
```

### 3. Worker entrypoint

Extend the existing `src/properties/entrypoints/worker.py` (which already handles `--queue extraction` and `--retry-job`) with `--queue enrichment`:

```python
async def _run_enrichment_worker() -> None:
    settings = Settings()
    setup_logging(settings.log_level)
    session = aioboto3.Session(...)
    container = await get_property_container()

    router = EventRouter()
    router.on(ENRICH_PROPERTY_REQUESTED_V1, handle_enrich_property_requested)

    consumer = SQSMessageConsumer(
        session=session,
        queue_url=settings.sqs_property_enrichment_queue_url,
        endpoint_url=settings.aws_endpoint_url,
    )
    worker = SQSWorker(
        consumer=consumer,
        router=router,
        context={"property_container": container},
        worker_name="property_enrichment_worker",
        use_heartbeat=True,
        heartbeat_interval=60,
        heartbeat_extension=120,
    )
    await worker.run()
```

Same shape as the existing extraction worker. Heartbeat is on as a safety net — typical run is ~2-3s (21 `find_nearby` calls at 5-way concurrency, each ~500ms), but rate-limited or slow Google responses can push individual calls into the 5-10s range. The heartbeat keeps the SQS visibility timeout from expiring mid-run.

### 4. Workflow handler + orchestrator

New file `src/properties/adapters/workers/enrichment_processor.py`:

```python
async def handle_enrich_property_requested(event: DomainEvent, context: dict) -> None:
    container = context["property_container"]
    payload = event.data
    await container.enrich_property.execute(
        property_id=UUID(payload["property_id"]),
        force=payload.get("force", False),
        requested_by_user_id=UUID(payload["requested_by_user_id"]),
    )
```

New use case `EnrichProperty` (the orchestrator) at `src/properties/application/use_cases/enrich_property.py`:

```python
class EnrichProperty:
    """Stage 1 + 2 of the POI enrichment workflow.

    1. Load the property, verify coordinates are set.
    2. Read the existing property_pois — identify skipped categories
       (those with at least one manually_edited row, unless force=True).
    3. For each category NOT in the skip set: call PlacesService.find_nearby
       per the category-to-place-types map, rank the results via
       proximity_ranker.rank_top_places. Track per-category failures.
    4. Provider-down guard: if every run category had zero results AND at
       least one category observed a failure, re-raise (see §9).
    5. Compose the final POI list:
         - Every existing row in SKIPPED categories (manual + auto — see §6)
         - All discovered rows for run categories
           (manually_edited=False, metadata={"provider": "google"})
    6. Persist via property_poi_repo.replace_for_property — atomic
       per-property replace.
    7. If force=True wiped any manually-edited rows, emit the audit
       warning (see §6a).
    8. Bump property aggregate_version.
    """

    def __init__(
        self,
        property_repo: PropertyRepository,
        property_poi_repo: PropertyPoiRepository,
        places_service: PlacesService,
    ) -> None:
        self.property_repo = property_repo
        self.property_poi_repo = property_poi_repo
        self.places_service = places_service

    async def execute(
        self,
        *,
        property_id: UUID,
        force: bool,
        requested_by_user_id: UUID,
    ) -> list[PropertyPoi]: ...
```

The category mapping (per ADR v4 §1, all 18 categories — multi-type categories like `PUBLIC_TRANSIT` produce multiple `find_nearby` calls):

```python
CATEGORY_TO_PLACE_TYPES: dict[PoiCategory, list[str]] = {
    PoiCategory.HOSPITAL:        ["hospital"],
    PoiCategory.BANK:            ["bank"],
    PoiCategory.GROCERY:         ["supermarket"],
    PoiCategory.SCHOOL:          ["school"],
    PoiCategory.PHARMACY:        ["pharmacy"],
    PoiCategory.GYM:             ["gym"],
    PoiCategory.RESTAURANT:      ["restaurant"],
    PoiCategory.COFFEE_SHOP:     ["cafe"],
    PoiCategory.LAUNDRY:         ["laundry"],
    PoiCategory.GAS_STATION:     ["gas_station"],
    PoiCategory.PUBLIC_TRANSIT:  ["bus_station", "subway_station", "train_station", "transit_station"],
    PoiCategory.KINDERGARTEN:    ["primary_school"],   # Google Places has no "kindergarten" — closest match
    PoiCategory.PARK:            ["park"],
    PoiCategory.POST_OFFICE:     ["post_office"],
    PoiCategory.LIBRARY:         ["library"],
    PoiCategory.SHOPPING_MALL:   ["shopping_mall"],
    PoiCategory.BAKERY:          ["bakery"],
    PoiCategory.POLICE_STATION:  ["police"],
}

DISCOVERY_RADIUS_METERS = 1500
TOP_N_PER_CATEGORY = 5
PLACES_CONCURRENCY_LIMIT = 5
```

These constants live in `enrich_property.py` for now. When the configurable-settings slice lands, they migrate to `_AppConstants`.

### 5. Discovery + ranking detail

Per-category coroutine (mirrors the existing pattern in `discover_property_amenities.py`, with one addition — the failure-flag return):

```python
@dataclass(frozen=True)
class CategoryDiscoveryResult:
    category: PoiCategory
    places: list[NearbyPlace]
    had_failures: bool   # True if ANY find_nearby call raised; used by §9 provider-down guard

async def _discover_category(
    self,
    category: PoiCategory,
    latitude: float,
    longitude: float,
) -> CategoryDiscoveryResult:
    place_types = CATEGORY_TO_PLACE_TYPES[category]
    all_places: list[NearbyPlace] = []
    had_failures = False
    for place_type in place_types:
        try:
            places = await self.places_service.find_nearby(
                latitude=latitude,
                longitude=longitude,
                place_type=place_type,
                radius_meters=DISCOVERY_RADIUS_METERS,
            )
            all_places.extend(places)
        except Exception:
            had_failures = True
            log.exception(
                "poi_discovery.find_nearby_failed",
                category=category.value,
                place_type=place_type,
            )
            # Soft failure: this place_type contributes zero results to
            # this category, but the worker continues. The flag is
            # rolled up by the orchestrator for the provider-down guard.
    # Dedup by place_id (multi-type categories like PUBLIC_TRANSIT can
    # return the same metro stop under both "subway_station" and
    # "transit_station").
    seen: set[str] = set()
    deduped: list[NearbyPlace] = []
    for p in all_places:
        if p.place_id and p.place_id in seen:
            continue
        if p.place_id:
            seen.add(p.place_id)
        deduped.append(p)
    return CategoryDiscoveryResult(category=category, places=deduped, had_failures=had_failures)
```

Stage 2 ranking — per category, look up `KNOWN_BRANDS_BY_CATEGORY.get(category.value)`, pass to `rank_top_places(...known_brands=brands, limit=TOP_N_PER_CATEGORY)`. (This is exactly the API the previous `refactor(properties): extract NearbyPlace + proximity ranker` commit set up.) After ranking, the orchestrator builds a dict `ranked_results: dict[PoiCategory, list[NearbyPlace]]` and rolls up `any_failures = any(r.had_failures for r in results)` for use in §9.

### 6. Manually-edited preservation

```python
existing = await self.property_poi_repo.list_by_property(property_id)

# A category is "skipped" if it contains ANY manually-edited row. Skipped
# means: leave the WHOLE category alone — both manual and auto rows survive
# the replace. Without this, auto-rows in a skipped category would get
# wiped (replace_for_property is atomic-per-property, not per-category).
skipped_categories: set[PoiCategory] = (
    set()
    if force
    else {poi.category for poi in existing if poi.manually_edited}
)

categories_to_run = [cat for cat in PoiCategory if cat not in skipped_categories]
```

The persistence step composes the final list:

```python
# Preserve EVERY existing row in skipped categories (manual + auto), then
# overlay newly-discovered rows for the categories we actually ran.
preserved_pois = [poi for poi in existing if poi.category in skipped_categories]
discovered_pois = [
    PropertyPoi(
        id=uuid4(),
        property_id=property_id,
        category=category,
        name=place.name,
        distance_meters=place.distance_meters,
        latitude=place.latitude,
        longitude=place.longitude,
        place_id=place.place_id,
        metadata={"provider": "google"},
        manually_edited=False,
    )
    for category, places in ranked_results.items()
    for place in places
]

final_list = preserved_pois + discovered_pois
await self.property_poi_repo.replace_for_property(
    property_id=property_id, pois=final_list,
)
await self.property_repo.bump_aggregate_version(property_id)
```

Two important properties of this composition:

- **Skipped categories preserve all their rows** — manual AND any auto rows that were already there from a previous discovery run. "Skip" means "leave alone," not "keep only the manual edits." Without this, an agent's one manual edit would silently delete the four auto-rows that coexisted with it in the same category.
- **Run categories get fully replaced** — pre-existing auto rows in the run set get wiped and re-inserted from the fresh discovery, which is the whole point of running the category.

The `replace_for_property` call is the same atomic-per-property delete + insert from the previous spec — preserved rows get **new ids** (the original ids are deleted and we re-insert). This is acceptable because:
- POI ids aren't referenced from anywhere else (no FKs into `property_pois`).
- The catalog as a whole is what matters; agents identify POIs by category/name/place_id.

If preserving ids becomes important later (e.g. front-end optimistic updates that track ids), the repo can grow a more granular `replace_by_categories` method. Out of scope here.

### 6a. The `force=True` audit log

When `force=True` causes the orchestrator to wipe pre-existing manually-edited rows, emit a structured warning:

```python
manual_count = sum(1 for poi in existing if poi.manually_edited)
if force and manual_count > 0:
    log.warning(
        "enrich_property.force_overwrote_manual_edits",
        property_id=str(property_id),
        wiped_count=manual_count,
        requested_by_user_id=str(requested_by_user_id),
    )
```

Useful for compliance review; no separate audit-log table.

### 7. Container wiring

`src/properties/container.py` — two new use cases conditional on their collaborators being present.

**New constructor args on `Container.__init__`** (matching the existing pattern — every auxiliary arg has a default so the container is constructible in test fixtures that don't need that branch):

```python
class Container:
    def __init__(
        self,
        # ... existing args ...
        enrichment_queue_url: str = "",
    ) -> None:
        # ... existing wiring ...
        self.enrichment_queue_url = enrichment_queue_url
```

**Use case wiring** (conditional, matches the existing `extract_property_owner_from_document` pattern):

```python
if command_publisher is not None and enrichment_queue_url:
    self.enqueue_enrich_property = EnqueueEnrichProperty(
        property_repo=property_repo,
        command_publisher=command_publisher,
        enrichment_queue_url=enrichment_queue_url,
    )
else:
    self.enqueue_enrich_property = None

if property_poi_repo is not None and places_service is not None:
    self.enrich_property = EnrichProperty(
        property_repo=property_repo,
        property_poi_repo=property_poi_repo,
        places_service=places_service,
    )
else:
    self.enrich_property = None
```

Bootstrap (`get_property_container`) reads `settings.sqs_property_enrichment_queue_url` and passes it as `enrichment_queue_url=` to `Container(...)`.

### 8. New event-type constant

`src/shared/events/types.py` — add:

```python
ENRICH_PROPERTY_REQUESTED_V1 = "ENRICH_PROPERTY_REQUESTED.v1"
```

This is a **command** (point-to-point on the SQS queue), not an SNS-fanned domain event — it does not need an SNS topic provisioned in `localstack-init.sh`.

### 9. Failure handling

Per ADR v7 §7.2 / §7.4:

- **Within a worker attempt**: Each `places_service.find_nearby` call's transient errors (rate limit, 5xx, network) are retried by the underlying adapter or via tenacity if it's wired in. Auth errors and 4xx-other re-raise immediately. (Slice doesn't add new retry logic — uses whatever the existing `GooglePlacesService` does.)
- **Per-place_type soft failure**: a 500 from Google for `bus_station` doesn't kill the `PUBLIC_TRANSIT` category — we log and proceed with the other place_types. The category contributes whatever results we got.
- **Per-category hard failure**: if every place_type for a category fails, that category contributes zero results — same as a category with genuinely no POIs nearby.
- **Provider-down guard**: if **every category** ends with zero results AND we observed at least one exception during stage 1, re-raise instead of persisting. This distinguishes "Google's API was unreachable" (retryable) from "this property is in the middle of nowhere with no POIs in radius" (legitimate empty result, persistable). Implementation: track an `any_failures: bool` and a `total_discovered: int` across the per-category coroutines; if `total_discovered == 0 and any_failures` → re-raise. Without this guard, a Google outage would silently overwrite the existing catalog with an empty list and bump aggregate_version.
- **Overall worker failure**: anything not caught at category-level bubbles up, the worker re-raises, SQS redelivers. After 5 attempts the message DLQs to `property-enrichment-dlq`. Ops triages via `properties.entrypoints.worker --queue enrichment-dlq` (exists already as a pattern — see `contract_intelligence` worker for the precedent).

The **partial-write policy** from ADR v7 §7.2 is satisfied implicitly: stage 1 is the only stage in this slice that does external I/O, and it either succeeds enough to produce a persistable list or re-raises before any DB write happens.

## Affected files / surfaces

- `src/properties/application/use_cases/enrich_property.py` — new (orchestrator)
- `src/properties/application/use_cases/enqueue_enrich_property.py` — new (HTTP-layer enqueue)
- `src/properties/adapters/workers/enrichment_processor.py` — new (worker handler)
- `src/properties/entrypoints/worker.py` — extend with `--queue enrichment` sub-command
- `src/properties/adapters/api/routes/properties.py` — add `POST /{property_id}/enrich` handler
- `src/properties/adapters/api/schemas.py` — add `EnrichPropertyRequest`
- `src/properties/container.py` — wire `enqueue_enrich_property` and `enrich_property` (both conditional on collaborators)
- `src/shared/events/types.py` — add `ENRICH_PROPERTY_REQUESTED_V1` constant
- `src/shared/config.py` — add `sqs_property_enrichment_queue_url` and `sqs_property_enrichment_dlq_url` settings
- `src/shared/entrypoints/bootstrap.py:get_property_container` — pass `enrichment_queue_url=settings.sqs_property_enrichment_queue_url`
- `scripts/localstack-init.sh` — add `property-enrichment-queue` + DLQ creation with redrive policy (mirror `property-extraction-queue` block)
- `.env.example` — document the new env var
- `README.md` — add the worker command (`uv run python -m properties.entrypoints.worker --queue enrichment`) to the worker list near the existing extraction worker
- Tests:
  - `tests/unit/properties/test_enqueue_enrich_property_use_case.py` — happy path, missing property → 404, missing coords → 422, command published with the right payload (assert on a tracking publisher)
  - `tests/unit/properties/test_enrich_property_use_case.py` — happy path produces 18 calls (one per category) on a tracking `PlacesService`, ranked output goes into `property_poi_repo.replace_for_property`, manually-edited categories are skipped (with `force=False`), `force=True` overrides, multi-type categories produce multiple `find_nearby` calls and dedupe by `place_id`, every persisted row has `manually_edited=False` and `metadata={"provider": "google"}`, `aggregate_version` is bumped
  - `tests/integration/test_property_pois.py` — extend with a `TestEnrichProperty` class: 202 on happy path (mocked `places_service` returns canned results), 401/403/404/422 paths, command actually arrives on the queue (assert via the in-memory command publisher fixture)

## Acceptance criteria

**Integration-level (FastAPI + in-memory adapters):**

- [ ] `POST /api/v1/admin/properties/{id}/enrich?organization_id=<uuid>` with `{"force": false}` returns `202` and queues an `ENRICH_PROPERTY_REQUESTED.v1` command on the in-memory command publisher.
- [ ] The command payload contains `property_id`, `organization_id`, `force`, `requested_by_user_id`.
- [ ] Cross-org call (caller is not a member of `organization_id`) → `403`.
- [ ] Unknown `property_id` → `404`.
- [ ] Property exists but has no coordinates → `422` with `Property missing coordinates`.
- [ ] No-auth → `401`.
- [ ] Endpoint does NOT do discovery synchronously — response time stays under typical HTTP latency budget regardless of how slow the (mocked) `PlacesService` would be.

**Unit-level (against in-memory adapters):**

*Enqueue use case:*

- [ ] `EnqueueEnrichProperty.execute` raises `PropertyNotFoundError` for missing or cross-org property — the command publisher is never called.
- [ ] `EnqueueEnrichProperty.execute` raises `PropertyMissingCoordinatesError` when lat/lon is None — the command publisher is never called.
- [ ] On the happy path, exactly one command is published with the right `event_type` (`ENRICH_PROPERTY_REQUESTED.v1`) and payload fields.

*Orchestrator:*

- [ ] `EnrichProperty.execute` calls `places_service.find_nearby` exactly once per `(category, place_type)` pair (verified via tracking `PlacesService`). For 18 categories with the multi-type `PUBLIC_TRANSIT` (4 types), that's 21 calls.
- [ ] All persisted rows have `manually_edited=False` and `metadata={"provider": "google"}`.
- [ ] When the property already has manually-edited rows in category X (and `force=False`), `find_nearby` is NOT called for any place_type belonging to X. The pre-existing manually-edited rows survive into the post-replace state with their original field values (id will differ — see §6).
- [ ] **Skipped category preservation:** when category X has 1 manually-edited + 4 auto-discovered rows and is skipped (`force=False`), all 5 rows survive the replace — auto rows are not silently wiped. (Verifies the §6 fix.)
- [ ] When `force=True`, manually-edited rows are wiped and discovery runs for every category.
- [ ] **Force audit log:** when `force=True` wipes N>0 manually-edited rows, the orchestrator emits a `log.warning("enrich_property.force_overwrote_manual_edits", ...)` with `property_id`, `wiped_count=N`, `requested_by_user_id`. (Verified by capturing structured log output.)
- [ ] Multi-type category dedup: if `bus_station` and `transit_station` both return a place with the same `place_id`, only one row gets persisted under `PUBLIC_TRANSIT`.
- [ ] `property.aggregate_version` is bumped exactly once per `execute` call.
- [ ] On a soft per-place_type failure (the `find_nearby` call raises), the category continues with whatever it got from the other place_types — no top-level re-raise.
- [ ] **Provider-down guard:** when EVERY `find_nearby` call raises (tracking PlacesService that always raises), the orchestrator re-raises and `replace_for_property` is NOT called. Pre-existing POIs in the repo survive intact.
- [ ] **Provider-down guard distinguishes from legitimate empty:** when every `find_nearby` returns `[]` (no exceptions), the orchestrator persists an empty list normally — does NOT re-raise.
- [ ] On a hard failure (the orchestrator's outer code raises), nothing is persisted (`replace_for_property` was not called).

**Regression:**

- [ ] All 510 pre-existing tests still green.
- [ ] The legacy `POST /api/v1/admin/property-amenities/discover` endpoint still works (untouched in this spec). It will be removed in the amenity-removal spec, after the dashboard is migrated.

## Open questions

- **`KINDERGARTEN` mapping.** Google Places has no `kindergarten` place_type; closest is `primary_school`, which is a superset. We accept the noise (some primary schools are not kindergartens) for now and let agents PATCH the misclassified rows. Flag if product wants a stricter heuristic — keyword filter for "creche", "infantário", etc. — before merge.
- **Worker concurrency.** `PLACES_CONCURRENCY_LIMIT=5` mirrors the existing amenity discovery. Leave alone unless the new categories (we're up from 9 to 18) push runtime into a problematic range.

## Resolved during sharpening (assumptions, not questions)

- **POI ids change on every `replace_for_property` call.** Acceptable per §6 — no FKs reference `property_pois`. If front-end optimistic updates need stable ids later, that's a follow-up to the repo port (a `replace_by_category` granular variant).
- **`metadata={"provider": "google"}` on every auto-discovered row.** Lets the future multi-provider slice decide its own re-discovery policy when tenants switch provider. **This slice does not commit to a behavior** for what happens to old-provider rows on switch — that's a deliberate question the multi-provider spec answers (re-discover all on switch? leave existing rows alone? per-property opt-in?). The signal exists; the policy is deferred.
- **No freshness tracking column on `property_pois`.** `created_at` is sufficient for ops queries. Slice doesn't need per-category retry-skipping; the API spend is bounded by the agent's clicks.
- **Constants live in code, not in `configurable_settings`.** No DB-backed runtime config in this slice. Categories list, radius, top-N, concurrency are Python constants. The configurable-settings spec is its own follow-up; it lands when cost-of-life needs proximity weights to be tunable.
- **`force=True` is audit-logged.** When `force=True` wipes manually-edited rows, the orchestrator emits a structured `log.warning("enrich_property.force_overwrote_manual_edits", property_id=..., wiped_count=N, requested_by_user_id=...)` line. Cheap, useful for compliance review, no separate audit-log table needed.
- **Provider-down detection.** Re-raise on `total_discovered == 0 AND any_failures` (see §9). Distinguishes "API is unreachable" (retry via SQS) from "this property has no nearby POIs" (legitimate persist). Without this guard, an API outage silently overwrites the catalog with empty results.

## Out of scope follow-ups

- **`2026-05-property-poi-multi-provider.md`** — `OverpassPlacesService` adapter, `PlacesService` factory selecting via `_AppConstants.PLACES_PROVIDER`, geo-cache decorator port. The `metadata={"provider": "google"}` we tag rows with in this slice is what makes that future migration sane (rows keep working; cache invalidates by provider key).
- **`2026-05-configurable-settings.md`** — DB-backed runtime config infrastructure (`_Constants` Pydantic model, `_AppConstants` loader with TTL refresh, `configurable_settings` table migration). First consumer is the multi-provider spec.
- **`2026-05-property-cost-of-life.md`** — stage 3 (`CostOfLifeService` + `CostScore` + `HouseholdComposition`), `ListingDerivedSignalsRepository` cross-context port, `property_listings` enrichment columns migration, cost-score override endpoint.
- **`2026-05-amenity-removal.md`** — depends on (1) this spec, (2) the dashboard frontend migration in `estate-os/src/app/(app)/imoveis/novo/actions.ts:44`. Drops the `property_amenities` table, `DiscoverPropertyAmenities`, `GetPropertyAmenities`, `AmenityCategory`, the `/property-amenities/*` routes, the related Supabase repo, and the leftover `NearbyPlace.to_dict/from_dict` jsonb-serialization helpers (only used by amenity).
- **`2026-XX-property-poi-embedding.md`** (deferred per ADR v8) — stage 4: OpenAI embedding generation + Pinecone storage.

## Commits

Per `_TEMPLATE.md` § Commits — `feat(properties)` for the workflow:

`feat(properties): POI auto-discovery workflow + ENRICH_PROPERTY_REQUESTED.v1 command`

Plus a follow-up `chore(events)` if the `localstack-init.sh` and config additions land separately (probably not — small enough to bundle).
