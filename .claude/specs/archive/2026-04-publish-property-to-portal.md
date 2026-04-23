# Publish property to the public portal

**Status:** shipped
**Owner:** Peter
**Created:** 2026-04-23
**Shipped:** 2026-04-23 (436 tests green; 32 new — 12 domain, 8 use case, 8 HTTP integration, 2 projection integration, 2 listings projector handler.)

## Problem

Today there is no way for an agent to say "this property is ready — put it on the portal." Properties are created in `DRAFT` status (`src/properties/application/use_cases/create_property.py:50`) and stay there: no use case, no route, and no domain method flips the status. The public portal endpoint (`GET /api/v1/listings/properties` → `list_active()` → filter `WHERE status = ACTIVE` in `src/listings/adapters/database/listing_repository.py:71`) therefore returns nothing for any real org, because every property is stuck in `DRAFT`.

The carried-state projector already handles `PROPERTY_CREATED.v1` / `PROPERTY_UPDATED.v1` / `PROPERTY_DELETED.v1` and writes every event into `property_listings` regardless of status (`src/listings/adapters/workers/property_event_handler.py:38-89`). So the read-side data is there — it's the business **transition** that's missing. Until we add a publish action, the pipeline works end-to-end but the portal is permanently empty.

We also want a distinct **business event** for the "went live" moment, not just another `PROPERTY_UPDATED.v1`. Future consumers (a "your listing is live" email, an analytics pipeline, a search indexer, an SEO ping service) all want to know specifically about publication, not every owner-detail tweak. One generic `UPDATED` doesn't give them a clean subscription.

## Goal

Agents can publish a property via `POST /properties/{property_id}/publish?organization_id=<uuid>` (mounted under whatever admin prefix the router already carries). The property's status flips from `DRAFT` (or `WITHDRAWN`) to `ACTIVE`, `aggregate_version` is bumped via the canonical repo path, a new `PROPERTY_PUBLISHED.v1` event is emitted with the same carried-state payload shape as `PROPERTY_CREATED.v1`, and the listings projector upserts the row so the property appears on the public portal on the next poll cycle.

## Non-goals

- **Unpublish / withdraw / re-publish.** `PROPERTY_UNPUBLISHED.v1` is the natural counterpart and will be a follow-on spec. Keep this one focused on the forward transition so it lands quickly.
- **New terminal transitions** (`SOLD` / `RENTED` markers). Those are separate business events; this spec doesn't touch them.
- **Changing the projector's write strategy.** Today it upserts every property event into `property_listings` regardless of status — that stays. Portal visibility is still a read-side filter (`WHERE status = ACTIVE`).
- **New preconditions beyond the minimum bar.** We enforce a small publishable-quality checklist (see Approach). Extra validations (photo count, pricing sanity, description length) are business polish for a future spec, not infrastructure.
- **Editing while published.** An `ACTIVE` property can still be edited through the existing owner/price/image use cases; those already emit `PROPERTY_UPDATED.v1`, which already updates the projector row. No dual-write gate in this spec.
- **Changing the event envelope.** `PROPERTY_PUBLISHED.v1` reuses `build_property_snapshot()` (the existing helper that produces the CREATED/UPDATED payload). No new shape, no new fields.
- **Frontend work.** The agencies-dashboard "Publish" button is a separate spec. This is a backend-only landing — the HTTP contract is documented below so the frontend spec can build against it.

## Approach

### 1. Domain: a new `publish()` method on `Property`

Add to `src/properties/domain/models/property.py` (exception goes in the existing `src/properties/domain/exceptions.py` alongside `PropertyNotFoundError`):

```python
# exceptions.py
class PropertyNotPublishableError(DomainError):
    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__(f"Property is not publishable: {', '.join(reasons)}")

# property.py
def publish(self) -> None:
    """Flip status to ACTIVE if the aggregate is publishable. Raises
    PropertyNotPublishableError otherwise. Does NOT bump aggregate_version
    — that's the use case's responsibility via the repo's atomic
    `bump_aggregate_version` method, matching every other update-style
    use case in this context (see `UpdatePropertyOwnerContact:46`)."""
    reasons: list[str] = []
    if self.status not in (PropertyStatus.DRAFT, PropertyStatus.WITHDRAWN):
        reasons.append(f"cannot_publish_from_status:{self.status.value}")
    if not self.address.strip():        reasons.append("missing_address")
    if not self.prices:                 reasons.append("missing_price")
    if not self.owners:                 reasons.append("missing_owner")
    if not self.images:                 reasons.append("missing_image")
    if reasons:
        raise PropertyNotPublishableError(reasons)
    self.status = PropertyStatus.ACTIVE
```

**Reasons are machine-readable codes** (`missing_address`, `cannot_publish_from_status:sold`, etc.) — the frontend renders its own localized copy. Decision resolved from the original open question.

The in-domain **`bump_version()` call is intentionally absent**. This differs from `CreateProperty` (spec:50 in the codebase) only because create is an *insert* — the initial write carries version=1. For updates, the canonical pattern is: mutate domain → targeted repo write → `bump_aggregate_version(property_id)` returns the refreshed aggregate with version N+1. See §2 and the reference implementation at `UpdatePropertyOwnerContact:45-48`.

### 2. Use case: `PublishProperty`

New file `src/properties/application/use_cases/publish_property.py`. **Mirrors `UpdatePropertyOwnerContact` exactly**, which is the established update-style pattern:

```python
class PublishProperty:
    def __init__(
        self,
        property_repo: PropertyRepository,
        domain_event_publisher: EventPublisher | None = None,
    ) -> None:
        self.property_repo = property_repo
        self.domain_event_publisher = domain_event_publisher

    async def execute(self, *, property_id: UUID, organization_id: UUID) -> Property:
        prop = await self.property_repo.get_by_id(property_id)
        if prop is None or prop.organization_id != organization_id:
            # Same "not-found-or-wrong-org collapses to 404" pattern as
            # DeleteProperty:47-53 — prevents cross-org probing.
            raise PropertyNotFoundError(str(property_id))

        prop.publish()  # raises PropertyNotPublishableError on gaps / wrong status

        await self.property_repo.update_status(property_id, PropertyStatus.ACTIVE)
        refreshed = await self.property_repo.bump_aggregate_version(property_id)
        await emit_property_published(self.domain_event_publisher, refreshed)
        return refreshed
```

`update_status` is a **new** port method — small, targeted, matching the `update_owner` / `save_price` / `save_image` style already on `PropertyRepository` (port at `src/properties/application/ports/repositories/property_repository.py:10`). A generic `update(prop)` was considered and rejected: every other write on the port is specific to the field it touches, which keeps the SQL surface small and audit-friendly.

`emit_property_published` is a new helper in `src/properties/application/events/property_event.py`, matching the existing `emit_property_deleted` / `emit_property_updated` helpers that peer use cases already call (see `delete_property.py:81`, `update_property_owner_contact.py:47`). Internally it wraps `build_property_snapshot` + `publisher.publish(...)` + the standard log-and-swallow on publish failure.

### 3. Event: `PROPERTY_PUBLISHED.v1`

Add to `src/shared/events/types.py`:

```python
PROPERTY_PUBLISHED_V1 = "PROPERTY_PUBLISHED.v1"
```

Payload is identical to `PROPERTY_CREATED.v1` — the same `build_property_snapshot(prop)` helper. No new fields.

Infrastructure (outside this repo): a new SNS topic `domain-events-PROPERTY_PUBLISHED-v1` (SNSEventPublisher converts `.v1` → `-v1` per the `types.py` docstring). The listings SQS queue subscribes to it alongside the existing CREATED / UPDATED / DELETED topics.

### 4. Listings projector: one-line registration + two docstring updates

`handle_property_event` at `src/listings/adapters/workers/property_event_handler.py:38-89` already does exactly what we need on every carried-state event: upsert by id from the snapshot, then emit the address-enrichment event. `PROPERTY_PUBLISHED.v1` has the same payload shape, so the handler works unchanged.

Add one line to `src/listings/entrypoints/events_worker.py` (the existing four-line block of `router.on(...)` calls, lines 64-67):

```python
router.on(PROPERTY_PUBLISHED_V1, handle_property_event)   # new
```

**Docstring updates** (not just code — these enumerate the handled event types and will be wrong after landing):

- `src/listings/adapters/workers/property_event_handler.py:3-7` — add PUBLISHED.v1 to the event-type list.
- `src/listings/entrypoints/events_worker.py:3-9` — add PUBLISHED.v1 to the topic list.

**Accepted side-effect**: publishing re-fires address enrichment. The projector emits `PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT.v1` on every applied upsert (`property_event_handler.py:69-73`), and publishing bumps `aggregate_version` so the upsert applies. A property published shortly after creation will see address enrichment run twice. Acceptable: the enrichment handler is idempotent, one extra LLM call per publish is cheap at current scale, and the alternative (conditional enrichment based on what changed) is a separate optimization spec.

### 5. Route: `POST /properties/{property_id}/publish`

Add to `src/properties/adapters/api/routes/properties.py`, right after the DELETE endpoint. The router's prefix is `/properties` (properties.py:20); the admin mount prefix is applied globally. `organization_id` is a **query parameter** — same pattern as GET and DELETE (properties.py:205, 237).

```python
@router.post(
    "/{property_id}/publish",
    summary="Publish a property to the public portal",
    description=(
        "Flip a property from DRAFT or WITHDRAWN to ACTIVE and broadcast "
        "PROPERTY_PUBLISHED.v1 so the listings context picks it up. "
        "Only the organization's OWNER or ADMIN can perform this action."
    ),
    responses={
        200: {"description": "Property published"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized — must be OWNER or ADMIN of the organization"},
        404: {"description": "Property not found"},
        422: {"description": "Property is not publishable (missing fields or wrong status)"},
    },
)
async def publish_property(
    property_id: UUID,
    organization_id: UUID,
    request: Request,
    member: tuple[User, Membership] = Depends(require_org_member),
):
    _user, membership = member
    role_value = membership.role.value if hasattr(membership.role, "value") else membership.role
    if role_value not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only OWNER or ADMIN can publish properties")

    publish_uc = request.app.state.property_container.publish_property
    try:
        prop = await publish_uc.execute(
            property_id=property_id,
            organization_id=organization_id,
        )
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")
    except PropertyNotPublishableError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": "Property is not publishable", "reasons": exc.reasons},
        )

    urls = await _generate_image_download_urls(request, prop)
    return _property_response(prop, urls)
```

Signature details taken from the real `delete_property` at properties.py:235-252 — `require_org_member` returns `tuple[User, Membership]`, role compares against `"owner" / "admin"` string values (not an enum), and the response includes pre-signed image URLs via `_generate_image_download_urls` to match the GET response shape.

`422` (not `400`) for `PropertyNotPublishableError` — the payload is well-formed; it's the aggregate's *state* that's invalid. The `reasons` array is a list of machine-readable codes the frontend renders to user-facing copy. Re-publishing an already-ACTIVE property surfaces the same 422 with `reasons=["cannot_publish_from_status:active"]` (falls out of the domain check; no extra code path needed).

### 6. Container wiring

`src/properties/container.py` — construct `PublishProperty` with the same `domain_event_publisher` that `CreateProperty` / `DeleteProperty` already use. One-line injection.

## Affected files / surfaces

**Events:**
- `src/shared/events/types.py` — add `PROPERTY_PUBLISHED_V1`.

**Properties (write side):**
- `src/properties/domain/exceptions.py` — add `PropertyNotPublishableError(DomainError)` carrying `reasons: list[str]`.
- `src/properties/domain/models/property.py` — add `publish()` method. (No `bump_version()` inside — that stays a use-case concern via the repo port.)
- `src/properties/application/ports/repositories/property_repository.py` — add abstract `update_status(property_id: UUID, status: PropertyStatus) -> None`.
- `src/properties/adapters/persistence/supabase_property_repo.py` — implement `update_status` (single `UPDATE` on the `status` column).
- `src/properties/adapters/inmemory/inmemory_property_repo.py` — in-memory implementation.
- `src/properties/application/events/property_event.py` — add `emit_property_published(publisher, prop)` helper.
- `src/properties/application/use_cases/publish_property.py` — **new** use case.
- `src/properties/adapters/api/routes/properties.py` — add `POST /{property_id}/publish` endpoint, reusing `_property_response` (properties.py:23) and `_generate_image_download_urls` (properties.py:75).
- `src/properties/container.py` — wire `publish_property`.

**Listings (read side):**
- `src/listings/entrypoints/events_worker.py` — one `router.on(...)` line + docstring update.
- `src/listings/adapters/workers/property_event_handler.py` — docstring update (no code change).

**Infrastructure (outside this repo — do not forget):**
- New SNS topic `domain-events-PROPERTY_PUBLISHED-v1`.
- Listings SQS queue subscribes to it.

**Tests:**
- `tests/unit/properties/test_property_domain_publish.py` — exercises `Property.publish()` directly. Cases: happy path from DRAFT, happy path from WITHDRAWN, each gap individually (missing address / price / owner / image), wrong source status (ACTIVE / SOLD / RENTED each produce the expected reason code), multiple gaps accumulate in `reasons`.
- `tests/unit/properties/test_publish_property_use_case.py` — uses `InMemoryPropertyRepository` + an in-memory event publisher (same double used in `test_create_property.py`). Cases: happy path emits `PROPERTY_PUBLISHED.v1` with snapshot matching `build_property_snapshot(prop)`; `bump_aggregate_version` is called and the returned aggregate has the new version; wrong org → `PropertyNotFoundError`; unknown id → `PropertyNotFoundError`; domain gaps bubble `PropertyNotPublishableError` without emitting an event; publish-failure is logged but not re-raised (matching `CreateProperty`).
- Add `tests/integration/test_property_event_projection.py` — POST `/publish` with a real FastAPI app + in-memory event publisher wired into the properties container; feed the emitted event through `handle_property_event`; assert the `property_listings` row exists with `status='active'` and the projector upsert is idempotent under replay. **Note:** the public `GET /api/v1/listings/properties` is intentionally *not* asserted here — it reads the legacy `ReadPropertyModel` (same `properties` table via `extend_existing=True`), which in tests uses `InMemoryListingRepository`, a separate in-memory store from the write side. That sync is a non-goal per the carried-state spec and isn't the point of this test. The "publish appears on the portal" behavior is covered at the properties-admin layer by `TestPublishProperty.test_publish_appears_in_list_active` (which hits `/admin/properties/active` over the same write-side data).
- `tests/e2e/test_property_admin_flow.py` (or extend existing) — `POST /publish` 200 on happy path, 422 with `reasons=["missing_image", ...]` when incomplete, 403 for non-admin, 404 for wrong org, 401 unauthenticated. Re-publish of an already-ACTIVE property returns 422 with `reasons=["cannot_publish_from_status:active"]`.

**Docs:**
- `docs/features/listings.md` — add a "Publishing a property" subsection explaining the DRAFT → ACTIVE flow, the publishable-quality checklist, and the HTTP contract. Also add a "Running the listings events worker" subsection with `uv run python -m listings.entrypoints.events_worker`, the event types it consumes (CREATED / UPDATED / DELETED / PUBLISHED / address-enrichment), and a pointer to the per-context worker pattern already documented elsewhere.
- `README.md` — add the listings events worker to the per-context workers list (currently lines ~459-461 show customers / bookings / properties events workers; listings is missing). One-line addition next to its siblings.

## Acceptance criteria

- [ ] `PROPERTY_PUBLISHED_V1` exists in `src/shared/events/types.py`.
- [ ] `Property.publish()` raises `PropertyNotPublishableError` (with machine-readable `reasons` codes) when status is not DRAFT/WITHDRAWN or when address / prices / owners / images are missing. Multiple gaps accumulate into one `reasons` list.
- [ ] `Property.publish()` does NOT bump `aggregate_version` itself — the use case drives the version bump via `property_repo.bump_aggregate_version(property_id)`, same as `UpdatePropertyOwnerContact`.
- [ ] `PropertyRepository.update_status` is a port method implemented by both Supabase and in-memory adapters.
- [ ] `PublishProperty.execute()` persists the status change, bumps aggregate_version atomically via the port, emits `PROPERTY_PUBLISHED.v1` via `emit_property_published`, and returns the refreshed aggregate. Publish-failure is logged but not re-raised.
- [ ] Emitted payload equals `build_property_snapshot(refreshed)` — bit-identical shape to `PROPERTY_CREATED.v1` / `PROPERTY_UPDATED.v1`.
- [ ] `POST /properties/{property_id}/publish?organization_id=<uuid>` returns 200 with `_property_response(prop, image_download_urls)`; 401 when unauthenticated; 403 when caller is not owner/admin; 404 when the id doesn't belong to the caller's org; 422 with `{"message": "...", "reasons": [...]}` for `PropertyNotPublishableError`, including the case of re-publishing an already-ACTIVE property.
- [ ] `handle_property_event` is registered for `PROPERTY_PUBLISHED_V1` in the listings worker. An integration test wires HTTP `POST /publish` → in-memory publisher → `handle_property_event` → `property_listings` row has `status='active'`. The follow-on "listings read path reads from `property_listings`" is out of scope per the carried-state spec's non-goal.
- [ ] Idempotency: replaying an older `PROPERTY_PUBLISHED.v1` (lower `source_aggregate_version`) does not regress the projector row — existing projector idempotency covers this; e2e test confirms.
- [ ] Docstrings in `property_event_handler.py` and `events_worker.py` list PROPERTY_PUBLISHED.v1 alongside the existing event types.
- [ ] `docs/features/listings.md` explains publishing a property AND how to run the listings events worker (`uv run python -m listings.entrypoints.events_worker`), including which event types it consumes. `README.md`'s per-context workers list includes the listings worker alongside its siblings.
- [ ] All unit, integration, and e2e tests above pass. Full suite green.

## Open questions

- **Publishable-bar: is "at least one image" the right floor?** Some agents want to stage listings without photos first. If feedback pushes back, relax to a warning (not a hard gate). Ship with strict; revisit if agents complain.

All other earlier open questions resolved in-spec:

- Reasons format → machine-readable codes (`missing_address`, `cannot_publish_from_status:<value>`), documented in §1.
- Org-scoping pattern → `get_by_id` + inline org check, matching `DeleteProperty` and `UpdatePropertyOwnerContact`.
- Version bump vs. persistence pattern → use case drives `update_status` + `bump_aggregate_version`, matching `UpdatePropertyOwnerContact`.
- Frontend scope → declared as non-goal; backend-only.

## Out of scope follow-ups

- **`PROPERTY_UNPUBLISHED.v1` + `POST /{id}/unpublish`.** Natural counterpart; flips `ACTIVE` → `WITHDRAWN`. Separate spec because it needs its own event type, route, and tests, and can land independently.
- **Agencies-dashboard "Publish" button.** Separate frontend spec that builds against the HTTP contract pinned above.
- **Terminal status transitions** (`SOLD`, `RENTED`) with their own business events — different spec.
- **Conditional address re-enrichment** — only re-fire `PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT.v1` when the `address` field actually changed. Optimization, not correctness.
- **Publish preview** ("show me what the portal card will look like before I commit"). Separate feature.
- **Bulk publish** of N properties in one request. Separate spec if agents start asking for it.
- **Publish auditing UI** — a log of who published what, when. The event is already persisted; surfacing it in the dashboard is a UX spec.
