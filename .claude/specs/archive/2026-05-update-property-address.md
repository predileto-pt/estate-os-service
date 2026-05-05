# Update property address (PATCH endpoint)

**Status:** shipped
**Owner:** Peter
**Created:** 2026-05-05
**Shipped:** 2026-05-05 (462 tests green; 26 new — 6 domain, 10 use case, 10 HTTP integration.)

## Problem

A property's `address` is set once at creation time (`src/properties/application/use_cases/create_property.py` via `POST /properties/`) and there is no path to change it afterward. The route table in `src/properties/adapters/api/routes/properties.py` exposes create / list / get / delete / publish — but **no PATCH** for the aggregate's own fields. Address typos, mid-listing relocations (e.g. fractional lot numbers corrected after a survey), and freshly-extracted addresses from a deed scan all require a database hand-fix today, which (a) bypasses domain invariants, (b) skips the `aggregate_version` bump, and (c) silently drifts the `property_listings` projection out of sync with the write-side row.

Owners-contact has already established the canonical update-style pattern at `src/properties/adapters/api/routes/property_owners.py:191-224` (`PATCH /{owner_id}/contact` → `UpdatePropertyOwnerContact` use case → repo `update_owner` + `bump_aggregate_version` + `emit_property_updated`). We need the same shape for the property's own address.

## Goal

Org members can update a property's address via `PATCH /properties/{property_id}/address?organization_id=<uuid>` with a body `{ "address": "<new value>" }`. The property's `address` is replaced, `aggregate_version` is bumped via the canonical repo path, and `PROPERTY_UPDATED.v1` is emitted with a fresh carried-state snapshot so the listings projector upserts the row on its next poll cycle.

## Non-goals

- **Patching other property fields.** No `description`, `typology`, `listing_type`, `latitude`, `longitude`, or `characteristics` mutations in this spec — each is its own narrow use case if/when needed, mirroring the existing per-field update pattern (owner-contact, image-order, etc.). Bundling them into one broad `PATCH /properties/{id}` would force conditional invariant checks per field and complicate the publishability gate.
- **Geocoding / address normalization / postal-code validation.** Address is a free-form `Text` column today (`src/properties/adapters/database/models.py:86`); this spec keeps it that way. Treating it as a structured value object is a separate concern.
- **Re-publishability gating on edit.** Per the shipped publish spec ("Editing while published. An `ACTIVE` property can still be edited through the existing owner/price/image use cases"), an `ACTIVE` property's address can be changed without flipping back to `DRAFT`. The listings projector already handles `PROPERTY_UPDATED.v1` regardless of status, so this is already the established behavior.
- **A new business event.** Address change is a generic update, not a "went live" / "withdrawn" / "sold" transition — `PROPERTY_UPDATED.v1` is the right envelope and reuses `build_property_snapshot()`.
- **Frontend work.** The agencies-dashboard "Edit address" affordance is a separate spec; this is backend-only. The HTTP contract below is documented so the frontend spec can build against it.

## Approach

### 1. Domain: `update_address()` on `Property`

Add to `src/properties/domain/models/property.py` alongside `publish()` (line 64):

```python
def update_address(self, new_address: str) -> None:
    """Replace the property's address. Strips surrounding whitespace and
    rejects empty input — `address` is `NOT NULL` and the publishability
    check at `publish()` already rejects whitespace-only values.
    Does NOT bump aggregate_version — the use case drives that via the
    repo's atomic bump_aggregate_version method, matching every other
    update-style use case.
    """
    cleaned = new_address.strip()
    if not cleaned:
        raise PropertyAddressInvalidError("address must not be empty")
    self.address = cleaned
```

New exception in `src/properties/domain/exceptions.py` next to `PropertyNotPublishableError`:

```python
class PropertyAddressInvalidError(DomainError):
    """Raised when an address update is rejected by domain invariants."""
```

The exception is distinct from `PropertyNotPublishableError` because the failure modes are different — `update_address` rejects a single bad input field, whereas publishability is a multi-field readiness check. Reasons stay simple here (string message, no codes list) since the only invariant is "non-empty"; if richer validation is added later (e.g. min-length, locale-specific format), upgrade the exception payload then.

### 2. Use case: `UpdatePropertyAddress`

New file `src/properties/application/use_cases/update_property_address.py`. Mirrors `UpdatePropertyOwnerContact` (`src/properties/application/use_cases/update_property_owner_contact.py:12-48`), including its **no-op short-circuit** on unchanged values:

```python
from uuid import UUID

from properties.application.events.property_event import emit_property_updated
from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.exceptions import PropertyNotFoundError
from properties.domain.models.property import Property
from shared.events.ports import EventPublisher


class UpdatePropertyAddress:
    def __init__(
        self,
        property_repo: PropertyRepository,
        domain_event_publisher: EventPublisher | None = None,
    ) -> None:
        self.property_repo = property_repo
        self.domain_event_publisher = domain_event_publisher

    async def execute(
        self,
        *,
        property_id: UUID,
        organization_id: UUID,
        address: str,
    ) -> Property:
        prop = await self.property_repo.get_by_id(property_id)
        if prop is None or prop.organization_id != organization_id:
            raise PropertyNotFoundError(str(property_id))

        # Domain validates + strips. We compare *after* normalization so a
        # PATCH with surrounding whitespace but identical content is a no-op.
        new_address = address.strip()
        if not new_address:
            # Defense-in-depth: schema also rejects, but the domain method is
            # the canonical invariant.
            prop.update_address(address)  # raises PropertyAddressInvalidError
        if new_address == prop.address:
            return prop

        prop.update_address(address)
        await self.property_repo.update_address(property_id, prop.address)
        refreshed = await self.property_repo.bump_aggregate_version(property_id)
        await emit_property_updated(self.domain_event_publisher, refreshed)
        return refreshed
```

Two notable differences from owner-contact:

1. **Org-scope check is in-line** (`prop.organization_id != organization_id` → 404), consistent with `PublishProperty` (`src/properties/application/use_cases/publish_property.py:36-37`). Owner-contact uses the route-level `_verify_property_ownership` helper (`src/properties/adapters/api/routes/property_owners.py:51-58`) instead. Both forms are in active use; we pick the in-line form here for symmetry with the most recently-shipped aggregate-level use case (`PublishProperty`).
2. **Calls `update_address` on the repo**, not `update_owner`. New port method below.

**No-op semantics:** if the stripped new address equals the current value, return the existing aggregate without writing, bumping `aggregate_version`, or emitting `PROPERTY_UPDATED.v1`. This matches owner-contact's per-field guard (`update_property_owner_contact.py:37,41`) and avoids redundant projector traffic on idempotent retries.

### 3. Repository port: `update_address()`

Add to `src/properties/application/ports/repositories/property_repository.py` next to `update_status` (line 49):

```python
@abstractmethod
async def update_address(self, property_id: UUID, address: str) -> None:
    """Persist an address change on a single property. The aggregate
    version bump is driven separately by `bump_aggregate_version`, same
    as every other update-style write on this port."""
    ...
```

Adapters to implement:

- **Supabase (Postgres) — production**: `src/properties/adapters/database/repositories.py` (class `SqlAlchemyPropertyRepository`, line 46; add the new method next to `update_status` at line 304). A targeted `UPDATE properties SET address = :address WHERE id = :property_id` against the SQLAlchemy model in `src/properties/adapters/database/models.py:86`. No `updated_at` write here — `bump_aggregate_version` already touches `updated_at` in the same logical operation.
- **In-memory — tests**: `src/properties/adapters/inmemory/inmemory_property_repo.py` (class `InMemoryPropertyRepository`, line 12; add next to `update_status` at line 68). Update `self._properties[property_id].address = address` and raise `PropertyNotFoundError` on miss, mirroring `update_status`.

### 4. HTTP route

Add to `src/properties/adapters/api/routes/properties.py` after the `delete_property` handler. **Mirror the owner-contact route shape** (path-style: aggregate-scoped sub-resource):

```python
@router.patch(
    "/{property_id}/address",
    response_model=PropertyResponse,
    summary="Update property address",
    responses={
        200: {"description": "Address updated (or unchanged — see no-op semantics)"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Property not found"},
        422: {"description": "Address failed schema validation (empty/whitespace-only)"},
    },
)
async def update_property_address(
    property_id: UUID,
    body: UpdatePropertyAddressRequest,
    organization_id: UUID,
    request: Request,
    _member: tuple[User, Membership] = Depends(require_org_member),
):
    update_uc = request.app.state.property_container.update_property_address
    try:
        prop = await update_uc.execute(
            property_id=property_id,
            organization_id=organization_id,
            address=body.address,
        )
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")

    urls = await _generate_image_download_urls(request, prop)
    return _property_response(prop, urls)
```

Permission model: **any org member** (just `require_org_member`, no OWNER/ADMIN gate). Rationale — owner-contact edits use the same level, and address is closer to a typo-fix than a destructive action. If product wants to lock this down to OWNER/ADMIN later, add the same role check used in `delete_property` / `publish_property`; the use case stays unchanged.

### 5. Request schema

New Pydantic model in `src/properties/adapters/api/schemas.py` next to `UpdatePropertyOwnerContactRequest` (line 65). The validator strips first, then enforces `min_length=1` so **both** empty (`""`) and whitespace-only (`"   "`) inputs reject with the same **422** schema-validation error — no domain-side leakage to a different status code:

```python
from pydantic import field_validator

class UpdatePropertyAddressRequest(BaseModel):
    address: str = Field(min_length=1, description="New street address; whitespace-only rejected")

    @field_validator("address")
    @classmethod
    def _strip_and_require_nonempty(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("address must not be empty")
        return cleaned
```

The domain method's strip + non-empty check (§1) remains as defense-in-depth — programmatic callers (workers, batch jobs) bypass the schema, so the invariant must be enforced at the aggregate boundary too. With the schema validator in place, the HTTP path will never hit the `PropertyAddressInvalidError` branch in normal use, which is why the route doesn't catch it: an unhandled domain error here would indicate a bug, and surfacing it as a 500 is the right signal.

### 6. Container wiring

Add to `src/properties/container.py` next to the existing `update_property_owner_contact` wiring (`src/properties/container.py:126-129`):

```python
self.update_property_address = UpdatePropertyAddress(
    property_repo=property_repo,
    domain_event_publisher=domain_event_publisher,
)
```

### 7. Event flow (no new types) — and a downstream side-effect to be aware of

`PROPERTY_UPDATED.v1` already carries the full snapshot via `build_property_snapshot()` (`src/properties/application/events/property_event.py:22-71`), and that snapshot already includes `address` (line 48). The listings projector (`src/listings/adapters/workers/property_event_handler.py`) upserts `property_listings.address` from this same key on every UPDATED event. Zero changes required to the projector or the event types module.

**Side-effect — re-enrichment is automatically triggered.** Every time the projector applies an upsert from a UPDATED event, it re-publishes `PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT.v1` carrying the new address (`src/listings/adapters/workers/property_event_handler.py:82-87`). For an address PATCH this is exactly what we want — parish / municipality / district must be re-resolved against the new address — but it has cost implications (geocoder budget). The no-op short-circuit in §2 ensures this fires only on actual changes, not on idempotent retries.

## Affected files / surfaces

- `src/properties/domain/models/property.py` — add `update_address()` method
- `src/properties/domain/exceptions.py` — add `PropertyAddressInvalidError`
- `src/properties/application/use_cases/update_property_address.py` — new use case
- `src/properties/application/ports/repositories/property_repository.py` — add `update_address` abstract method
- `src/properties/adapters/database/repositories.py` — implement `update_address` on `SqlAlchemyPropertyRepository` (next to `update_status` at line 304)
- `src/properties/adapters/inmemory/inmemory_property_repo.py` — implement `update_address` on `InMemoryPropertyRepository` (next to `update_status` at line 68)
- `src/properties/adapters/api/schemas.py` — add `UpdatePropertyAddressRequest` with `field_validator` strip+non-empty
- `src/properties/adapters/api/routes/properties.py` — add `PATCH /{property_id}/address` handler
- `src/properties/container.py` — wire `UpdatePropertyAddress`
- Tests (existing flat layout — no new subfolders):
  - `tests/unit/properties/test_property_domain_update_address.py` — invariants: empty rejects, whitespace-only rejects, valid value strips and replaces. Sibling to `test_property_domain_publish.py`.
  - `tests/unit/properties/test_update_property_address_use_case.py` — load → mutate → repo update → bump_version → emit happy path; cross-org load returns 404 *before* any write; **no-op short-circuit** asserts that an unchanged value yields zero repo writes / zero version bumps / zero emissions. Sibling to `test_publish_property_use_case.py`.
  - `tests/integration/test_properties.py` — add a `TestUpdatePropertyAddress` class (mirrors `TestUpdatePropertyOwnerContact` at `tests/integration/test_property_owners.py:229`): 200 on happy path with bumped version + stripped address in response, 422 on empty / whitespace-only body, 404 on cross-org and missing id, 200 with unchanged version on no-op. `PROPERTY_UPDATED.v1` emission asserted via the existing in-memory test event publisher pattern used by `test_publish_property_use_case.py`.
- Docs: no architecture change → no doc updates required

## Acceptance criteria

- [ ] `PATCH /properties/{property_id}/address?organization_id=<uuid>` with `{"address": "Rua das Flores 12, 1100-123 Lisboa"}` returns `200` with the refreshed `PropertyResponse`, `aggregate_version` bumped by exactly 1.
- [ ] Response body's `address` equals the **stripped** input — `"  Rua X  "` round-trips as `"Rua X"`.
- [ ] Empty (`""`) and whitespace-only (`"   "`) inputs both return **422** (Pydantic schema validation), not 400 — the schema validator strips before length-check so both cases land on the same status.
- [ ] **No-op semantics:** PATCHing the current address (or a whitespace variant of it) returns `200` with the unchanged property; `aggregate_version` is unchanged; **no** `PROPERTY_UPDATED.v1` is emitted; **no** repo write occurs.
- [ ] Property in another organization returns `404` (does not leak existence).
- [ ] Non-existent property returns `404`.
- [ ] No auth → `401`. Auth but not a member of the org → `403` (handled by `require_org_member`).
- [ ] On a successful change, `PROPERTY_UPDATED.v1` is published exactly once with `data.address` equal to the stripped new value and `data.aggregate_version` matching the response.
- [ ] Calling on a property in `ACTIVE` status succeeds (no publishability re-check). Status is preserved.
- [ ] Domain unit test: `prop.update_address("  ")` raises `PropertyAddressInvalidError`; `prop.update_address("  X  ")` sets `address == "X"`.
- [ ] Use case unit test: cross-org call raises `PropertyNotFoundError` *before* any repo write or event emission.
- [ ] All existing tests still green.

## Open questions

- **Should we require OWNER/ADMIN role?** Default in this spec is "any org member" (matches owner-contact). Flag for product confirmation before merge — if the answer is "admin-only," add the same role gate used by `publish_property` / `delete_property`. Not blocking implementation; the use case is permission-agnostic.
- **Audit trail / who changed what?** Currently no per-field audit log exists for any property mutation. If we want one, it's a cross-cutting spec — not bolted on here.

## Resolved during sharpening (assumptions, not questions)

- **No-op write behavior** — short-circuit on unchanged value (matches owner-contact). See §2 and AC.
- **Empty/whitespace input status code** — uniformly **422** via a Pydantic `field_validator` that strips before length-check. The domain method's invariant remains for non-HTTP callers. See §1, §5, AC.
- **Org-scope check placement** — in-line in the use case, consistent with `PublishProperty`. The route helper pattern from owner-routes is also valid; we pick one for symmetry, not as a project-wide rule.

## Out of scope follow-ups

- `PATCH /properties/{property_id}` covering `description`, `typology`, `listing_type`, lat/lng, `characteristics` — each as its own narrow use case (or one bundled patch with explicit field-level invariant routing). Decide once we have a second mutable field requested.
- Address as a structured value object (street / number / postal code / locality) with locale-aware validation. Pre-requisite for a "geocode on save" pipeline.
- Webhook / outbox observability for emitted `PROPERTY_UPDATED.v1` events from this path — covered by the existing event-bus monitoring spec.
