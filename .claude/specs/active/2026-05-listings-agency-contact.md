# Listings — agency contact on the projection

**Status:** in-progress
**Owner:** Peter
**Created:** 2026-05-11

## Problem

The public listing detail endpoint exposes property data but no agency context. The portal FE wants to render an agency card (name, email, phone) above the chatbot on each listing page. The `property_listings` projection carries only `organization_id` (UUID); the agency's display fields live elsewhere.

## Goal

`GET /api/v1/listings/properties/{id}` (and the admin variant) returns an `agency` block — `{name, email, phone}` — denormalized onto each `property_listings` row. No new JOIN on the read path.

## Non-goals

- A dedicated `Organization.email` / `Organization.phone` column. Resolved decision: pull contact from the **creating user** (`Organization.created_by → users.{email, phone}`) — agencies are SMB-shaped, the admin user is the contact.
- `ORGANIZATION_UPDATED.v1` events. Resolved decision: projector resolves agency contact on each `PROPERTY_*` event (renames propagate on the next property write — acceptable, renames are rare).
- Including the agency block in the list response (`GET /properties`) — only the detail endpoint in v1. Trivial follow-up if needed.
- Multi-contact / role-based contacts (sales vs. property manager).
- Internationalization of the contact card.
- Frontend implementation (lives in the portal repo).

## Approach

### 1. Schema — three nullable columns on `property_listings`

```sql
ALTER TABLE property_listings
  ADD COLUMN agency_name  TEXT NULL,
  ADD COLUMN agency_email TEXT NULL,
  ADD COLUMN agency_phone TEXT NULL;
```

Nullable so the column add is safe on the live table; values populate as projector events flow + via the backfill script. No index — read access is always by `id` (already PK).

### 2. New port — `GetAgencyContact` in `listings/application/ports/`

```python
@dataclass(frozen=True)
class AgencyContact:
    name: str | None
    email: str | None
    phone: str | None

class GetAgencyContact(Protocol):
    async def execute(self, organization_id: UUID) -> AgencyContact: ...
```

- Returns an `AgencyContact` with all three fields `None` when the org row is gone — projector still writes the row, just with NULL agency columns. Defensive against deleted/orphaned orgs.

### 3. Adapter — `organizations` side

`organizations.adapters.composition.get_agency_contact.GetAgencyContactAdapter` (location TBD at implementation time):

```python
class GetAgencyContactAdapter:
    def __init__(self, org_repo, user_repo): ...
    async def execute(self, organization_id: UUID) -> AgencyContact:
        org = await self._org_repo.get_by_id(organization_id)
        if org is None: return AgencyContact(None, None, None)
        user = await self._user_repo.get_by_id(org.created_by)
        name  = org.name
        email = user.email if user else None
        phone = user.phone.full() if user and user.phone else None  # PhoneNumber → "+351..."
        return AgencyContact(name, email, phone)
```

Wired in `shared/entrypoints/bootstrap.py`: instantiated with the existing org + identity repos and injected into the listings container.

### 4. Projector wiring

`handle_property_event` (in `listings/adapters/workers/property_event_handler.py`) calls the port on each `PROPERTY_CREATED/UPDATED/PUBLISHED` event and passes the result into `upsert_from_event`:

```python
agency = await context["get_agency_contact"].execute(UUID(data["organization_id"]))
await repo.upsert_from_event(event_data=data, source_occurred_at=occurred_at, agency=agency)
```

`upsert_from_event` widens to accept `agency: AgencyContact | None = None`; `_event_to_row` adds the three columns. The UPDATE SET set (the existing conflict-resolution code) includes the new agency columns so they refresh on every PROPERTY_UPDATED. Location and embedding columns stay excluded as today.

### 5. Detail-endpoint response

`GET /api/v1/listings/properties/{id}` response gains a top-level block:

```json
{
  "id": "...",
  "title": "...",
  // existing fields ...
  "agency": {
    "name": "Predileto Imobiliária",
    "email": "agent@predileto.pt",
    "phone": "+351 912 345 678"
  }
}
```

All three sub-fields are nullable. The block is **always present** (never omitted), even when every sub-field is `null` — keeps the response shape stable for FE consumers.

### 6. Backfill

A one-shot CLI: `uv run python -m listings.entrypoints.backfill_agency_contact`. Iterates every existing `property_listings` row, calls `GetAgencyContact`, writes the columns. Idempotent. No event bus.

### 7. Tests

- Unit test for `GetAgencyContactAdapter` (org found / user found / both missing).
- Projector integration test: simulate `PROPERTY_CREATED.v1`; assert agency columns populated.
- Repo integration test: `upsert_from_event` with an `agency` kwarg writes the three columns; later UPDATE refreshes them.
- HTTP integration test on the detail endpoint: response body includes the `agency` block.

## Affected files / surfaces

- **Edit**: `src/listings/adapters/database/property_listing_model.py` — add 3 columns.
- **New**: alembic migration `add_agency_columns_to_property_listings`.
- **Edit**: `src/listings/domain/property_listing.py` — add `agency_name`, `agency_email`, `agency_phone` (or a nested `AgencyContact` value object — pick one at implementation time; lean toward 3 flat fields to keep the projection denormalized).
- **New**: `src/listings/application/ports/get_agency_contact.py` — `AgencyContact` + `GetAgencyContact` Protocol.
- **New**: `src/organizations/adapters/composition/get_agency_contact.py` (or similar) — adapter impl.
- **Edit**: `src/listings/container.py` — accept + expose `get_agency_contact` port.
- **Edit**: `src/shared/entrypoints/bootstrap.py` — wire the adapter into the listings container.
- **Edit**: `src/listings/adapters/workers/property_event_handler.py` — call the port + pass agency to upsert.
- **Edit**: `src/listings/adapters/database/property_listing_repository.py` — `upsert_from_event` accepts `agency`; `_event_to_row` (or a wrapper) writes the three columns.
- **Edit**: `src/listings/adapters/inmemory/inmemory_property_listing_repo.py` — mirror the same upsert signature so existing tests keep passing.
- **Edit**: `src/listings/adapters/api/routes/listings.py` — detail-endpoint response builder gains the `agency` block.
- **New**: `src/listings/entrypoints/backfill_agency_contact.py` — backfill CLI.
- **Tests**: unit + integration as listed in §7.
- **Docs**: short note in README's "Property Listings" section.

## Acceptance criteria

- [ ] Alembic migration adds the three columns (nullable). `bash scripts/migrate_admin.sh upgrade head` and inverse both clean.
- [ ] `PropertyListingModel` carries the three columns; `PropertyListing` domain model carries them too.
- [ ] `GetAgencyContact` port + adapter resolve the contact from `Organization` + `User(created_by)`. Returns `AgencyContact(None, None, None)` for missing org.
- [ ] Projector on `PROPERTY_CREATED/UPDATED/PUBLISHED` writes the three columns. Confirmed by integration test.
- [ ] UPDATE on a later event refreshes the agency columns (not in the excluded set).
- [ ] `GET /api/v1/listings/properties/{id}` returns an `agency: {name, email, phone}` block. All three sub-fields nullable; block always present.
- [ ] Backfill CLI populates the columns for all existing rows; idempotent on re-run.
- [ ] In-memory listings repo accepts the `agency` kwarg with the same semantics so existing integration tests pass unchanged.
- [ ] Existing tests still pass after the projector wiring change.

## Open questions

- **Phone format**: store as the formatted `+351 912 345 678` or as a structured `{country_code, number}` mirror of `PhoneNumber`? Lean toward formatted string in the projection (denormalized denormalization). Confirm at implementation time.

## Out of scope follow-ups

- Add the `agency` block to the list endpoint (`GET /properties`) — straightforward once columns are projected.
- Dedicated `Organization.email` + `Organization.phone` fields if/when agencies need a contact distinct from any user.
- `ORGANIZATION_UPDATED.v1` events for live-refreshing agency columns without a downstream property write.

## Commits

- `feat(listings): add agency columns to property_listings projection`
- `feat(listings): GetAgencyContact port + projector wiring`
- `feat(listings): expose agency block on detail endpoint`
- `chore(listings): backfill agency contact for existing rows`
