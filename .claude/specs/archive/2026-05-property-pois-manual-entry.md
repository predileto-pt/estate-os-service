# Property POIs — manual entry surface

**Status:** shipped
**Owner:** Peter
**Created:** 2026-05-08
**Shipped:** 2026-05-08 (507 tests green; 33 new — 17 unit, 16 HTTP integration.)

## Problem

ADR-010 (v4-v7) commits a property-enrichment workflow that discovers POIs (points of interest), ranks them, and computes a cost-of-life score on the listing. The full workflow has many moving pieces (command queue, multi-provider `PlacesService`, geo-cache, configurable settings, cross-context derived-signals port, …) — landing it as one PR would be unreviewable.

This spec is **the foundation slice**: the POI domain model, repository, and the manual-entry HTTP surface. Agents can create, list, edit, and delete POIs by hand from the dashboard, with all the metadata fields the auto-discovery workflow will eventually populate. No discovery, no workflow, no cost score in this spec — those are explicit follow-ups.

Why this slice first: every later spec depends on `PropertyPoi` existing in the domain, the table existing in the schema, and the repository port being wired. Shipping the substrate first means each follow-up is small and additive.

## Goal

Agents can manage a property's POI catalog directly via the admin API:

- `POST /api/v1/admin/properties/{id}/pois` — replace the entire catalog with a list of POIs (each carrying optional custom JSON metadata). Sets `manually_edited=true` on every row.
- `GET /api/v1/admin/properties/{id}/pois` — list the property's POIs.
- `PATCH /api/v1/admin/properties/{id}/pois/{poi_id}` — edit one POI in place. Sets `manually_edited=true`.
- `DELETE /api/v1/admin/properties/{id}/pois/{poi_id}` — remove one POI.

Auth via `require_org_member` (or stricter — flag in open questions). The endpoints route through the existing `request.app.state.property_container`; the container itself gains a new optional `property_poi_repo` constructor arg, four conditionally-wired use cases, and one new line in the bootstrap (see §7).

## Non-goals

- **Auto-discovery / workflow trigger / worker.** No `POST /enrich` endpoint, no `ENRICH_PROPERTY_REQUESTED.v1` command, no `PlacesService` integration. Next spec.
- **Cost score on `property_listings`.** Schema migration 2 from ADR §6.2 (the `property_listings` enrichment columns) is **not in this spec**. Lands with the cost-of-life spec where it has a consumer.
- **Configurable settings infrastructure.** ADR §6.3 (`configurable_settings` table) is also deferred — its first consumer is the workflow spec (provider selection, proximity weights). Shipping infra without consumers means reviewing a mechanism nobody is using yet; defer.
- **Touching the existing `property_amenities` table or `DiscoverPropertyAmenities` use case.** Per ADR v4 §locked-decisions row 2: existing amenity code stays as-is.
- **`replace_property_pois` partial-merge or upsert semantics.** POST replaces the entire catalog. If an agent wants to edit one POI without re-submitting, they use PATCH.

## Approach

### 1. Domain: `PropertyPoi` + `PoiCategory`

Per ADR v4 §1, exact shape. New file `src/properties/domain/models/property_poi.py`:

```python
from __future__ import annotations
import enum
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


class PoiCategory(str, enum.Enum):
    HOSPITAL = "hospital"
    BANK = "bank"
    GROCERY = "grocery"
    SCHOOL = "school"
    PHARMACY = "pharmacy"
    GYM = "gym"
    RESTAURANT = "restaurant"
    COFFEE_SHOP = "coffee_shop"
    LAUNDRY = "laundry"
    GAS_STATION = "gas_station"
    PUBLIC_TRANSIT = "public_transit"
    KINDERGARTEN = "kindergarten"
    PARK = "park"
    POST_OFFICE = "post_office"
    LIBRARY = "library"
    SHOPPING_MALL = "shopping_mall"
    BAKERY = "bakery"
    POLICE_STATION = "police_station"


@dataclass
class PropertyPoi:
    id: UUID
    property_id: UUID
    category: PoiCategory
    name: str
    distance_meters: float
    latitude: float
    longitude: float
    place_type: str | None = None
    place_id: str | None = None
    metadata: dict = field(default_factory=dict)
    manually_edited: bool = False
    created_at: datetime | None = None  # set by the adapter on insert
    updated_at: datetime | None = None
```

No domain methods in this spec — POIs are passive data records. Mutations happen in use cases.

### 2. Schema migration

Single alembic migration matching ADR §6.1 verbatim — `add_property_pois_table`. Creates the `poi_category` postgres enum (all 18 values), the `property_pois` table with `metadata jsonb default '{}'`, two indexes (`property_id`, `(property_id, category)`), the `update_updated_at_column()` trigger, and the row-level security policy for service-role.

Filename: `alembic/versions/<timestamp>_<rev>_add_property_pois_table.py`. Revision generated via `uv run alembic revision -m "add property_pois table"` — let alembic pick the SHA.

**No data migration from `property_amenities`.** Different shapes; per ADR §6.5 explicit non-goal.

### 3. Repository port + adapters

Port at `src/properties/application/ports/repositories/property_poi_repository.py`:

```python
from abc import ABC, abstractmethod
from uuid import UUID

from properties.domain.models.property_poi import PoiCategory, PropertyPoi


class PropertyPoiRepository(ABC):
    @abstractmethod
    async def list_by_property(self, property_id: UUID) -> list[PropertyPoi]: ...

    @abstractmethod
    async def get_by_id(self, poi_id: UUID) -> PropertyPoi | None: ...

    @abstractmethod
    async def replace_for_property(
        self, *, property_id: UUID, pois: list[PropertyPoi]
    ) -> list[PropertyPoi]:
        """Atomically replace the entire POI catalog for one property.
        Existing rows are deleted; the new list is inserted with
        `manually_edited=true` on every row. Returns the persisted rows
        with their new ids and timestamps."""
        ...

    @abstractmethod
    async def update(self, poi: PropertyPoi) -> PropertyPoi:
        """Update a single POI by id. Caller is responsible for setting
        `manually_edited=true` if appropriate (the manual-edit use case
        does this; future auto-discovery writes from the worker do not)."""
        ...

    @abstractmethod
    async def delete(self, poi_id: UUID) -> bool:
        """Returns True if the row existed and was deleted."""
        ...
```

**Adapters:**
- `src/properties/adapters/persistence/supabase_property_poi_repo.py` — new file with `SupabasePropertyPoiRepository`. Mirrors `SupabasePropertyAmenityRepository` (`src/properties/adapters/persistence/supabase_property_amenity_repo.py`) — wraps `supabase.AsyncClient`, uses `_to_domain` / `_to_row` helpers, lets the DB defaults populate `id` / `created_at` / `updated_at` on insert. **Production uses Supabase HTTP-client adapters for everything in the properties context** (see existing `SupabasePropertyRepository`, `SupabasePropertyAmenityRepository`, `SupabaseExtractionJobRepository`). The vestigial `SqlAlchemyPropertyRepository` at `src/properties/adapters/database/repositories.py` is not wired in production; we follow the Supabase pattern, not that one.
- `src/properties/adapters/inmemory/inmemory_property_poi_repo.py` — new file, parallels `inmemory_property_repo.py`'s style. `_pois: dict[UUID, PropertyPoi]` keyed by id; helpers index by property_id.

The `replace_for_property` adapter implementation runs `DELETE … WHERE property_id = :pid` followed by bulk insert of the new list. PostgREST has no transactional batch primitive, so the small race window where the property has zero POIs between delete and insert is accepted — agents triggering replace are interactive humans, not concurrent writers, and any concurrent reader gets a consistent intermediate state. The in-memory adapter does the equivalent (delete-then-extend on the dict).

**Empty list is valid**: `POST /pois` with `pois: []` clears the property's catalog. Replace semantics; if the agent meant something else, they wouldn't send `[]`.

### 4. Use cases

Four use cases under `src/properties/application/use_cases/`:

- `replace_property_pois.py` — `ReplacePropertyPois`. Loads the property and checks `prop.organization_id == organization_id` inline (404 on mismatch), validates each input row's coordinates, calls `repo.replace_for_property` with `manually_edited=True` on every row, **bumps `aggregate_version` via `property_repo.bump_aggregate_version`** so the listings projector picks up the change, returns the persisted list.
- `update_property_poi.py` — `UpdatePropertyPoi`. Inline org-scope check. Loads the POI by id, verifies it belongs to the requested property (404 if not — prevents cross-property edits via direct id), applies the patch fields, sets `manually_edited=True`, **bumps `aggregate_version`**, returns the updated row.
- `delete_property_poi.py` — `DeletePropertyPoi`. Same inline org + cross-property checks; calls `repo.delete`. **Bumps `aggregate_version`.**
- `list_property_pois.py` — `ListPropertyPois`. Pure read. Inline org-scope check. Returns `repo.list_by_property`. No `aggregate_version` bump — read-only.

**Org-scope check is inline in each use case**, matching the recent pattern from `PublishProperty` (`src/properties/application/use_cases/publish_property.py:36-37`) and `UpdatePropertyAddress`. We deliberately do **not** use the route-level `_verify_property_ownership` helper from `src/properties/adapters/api/routes/property_owners.py:51-58` — that's an older pattern, and the inline form puts the security check next to the load. Both forms are in active use in the codebase; new aggregate-level use cases use inline.

### 5. HTTP routes

New file `src/properties/adapters/api/routes/property_pois.py`. Mirrors `property_owners.py` for the file shape (router, response converter helper) — but **does not** import or replicate `_verify_property_ownership`. Cross-org and cross-property defense lives inside the use cases (see §4). Routes only: parse the body, call the use case, map domain exceptions to HTTP codes.

Endpoints (all gated by `require_org_member` for authentication; cross-org / cross-property checks happen inside the use case via `PropertyNotFoundError`):

| Method | Path | Use case | Status |
|---|---|---|---|
| `POST` | `/api/v1/admin/properties/{property_id}/pois` | `ReplacePropertyPois` | 200, returns the persisted list |
| `GET` | `/api/v1/admin/properties/{property_id}/pois` | `ListPropertyPois` | 200 |
| `PATCH` | `/api/v1/admin/properties/{property_id}/pois/{poi_id}` | `UpdatePropertyPoi` | 200 |
| `DELETE` | `/api/v1/admin/properties/{property_id}/pois/{poi_id}` | `DeletePropertyPoi` | 204 |

Mounted in `src/shared/main.py` at `/api/v1/admin` next to `property_amenities.router`:

```python
from properties.adapters.api.routes import property_pois
app.include_router(property_pois.router, prefix="/api/v1/admin")
```

Why POST not PUT for replace: matches the user-stated preference in ADR v4 §2 ("POST /api/v1/admin/properties/{id}/pois — sync replace-all"). PUT would also work semantically; POST is the user's choice.

### 6. Pydantic schemas

In `src/properties/adapters/api/schemas.py`:

```python
class PropertyPoiBase(BaseModel):
    category: PoiCategory
    name: str = Field(min_length=1, max_length=200)
    distance_meters: float = Field(ge=0)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    place_type: str | None = None
    place_id: str | None = None
    metadata: dict = Field(default_factory=dict)


class CreatePropertyPoiRequest(PropertyPoiBase):
    pass


class ReplacePropertyPoisRequest(BaseModel):
    pois: list[CreatePropertyPoiRequest] = Field(default_factory=list, max_length=200)


class UpdatePropertyPoiRequest(BaseModel):
    """All fields optional — PATCH semantics."""
    category: PoiCategory | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    distance_meters: float | None = Field(default=None, ge=0)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    place_type: str | None = None
    place_id: str | None = None
    metadata: dict | None = None


class PropertyPoiResponse(PropertyPoiBase):
    id: UUID
    property_id: UUID
    manually_edited: bool
    created_at: datetime
    updated_at: datetime
```

The `metadata` field is intentionally untyped (`dict`) — agents and the future workflow store provider-specific extras (Google ratings, OSM tags, agent notes) without us pre-defining the keys.

### 7. Container wiring

`src/properties/container.py` — add `property_poi_repo: PropertyPoiRepository | None = None` to `Container.__init__` (matches every other auxiliary repo / service signature in this container — all are `Optional` with `None` defaults). Wire the four use cases conditionally:

```python
self.property_poi_repo = property_poi_repo
if property_poi_repo is not None:
    self.replace_property_pois = ReplacePropertyPois(
        property_repo=property_repo, property_poi_repo=property_poi_repo
    )
    self.update_property_poi = UpdatePropertyPoi(
        property_repo=property_repo, property_poi_repo=property_poi_repo
    )
    self.delete_property_poi = DeletePropertyPoi(
        property_repo=property_repo, property_poi_repo=property_poi_repo
    )
    self.list_property_pois = ListPropertyPois(
        property_repo=property_repo, property_poi_repo=property_poi_repo
    )
else:
    self.replace_property_pois = None
    self.update_property_poi = None
    self.delete_property_poi = None
    self.list_property_pois = None
```

The conditional pattern matches the existing `extract_property_owner_from_document` wiring at `src/properties/container.py:113-122` — auxiliary use cases that depend on optional collaborators are present-or-None on the container, never raising at construction time.

Bootstrap (`src/shared/entrypoints/bootstrap.py:get_property_container`) wires `property_poi_repo=SupabasePropertyPoiRepository(client)` — same `AsyncClient` the existing Supabase repos receive (`SupabasePropertyAmenityRepository(client)` at line 241 of bootstrap.py is the precedent).

### 8. Test infrastructure (conftest)

`tests/conftest.py` gains a `property_poi_repo` fixture (returns `InMemoryPropertyPoiRepository()`) and the existing `property_container` fixture grows a new arg. No new top-level fixtures beyond `property_poi_repo`.

## Affected files / surfaces

- `src/properties/domain/models/property_poi.py` — new (`PropertyPoi`, `PoiCategory`)
- `src/properties/application/ports/repositories/property_poi_repository.py` — new port
- `src/properties/adapters/persistence/supabase_property_poi_repo.py` — new (`SupabasePropertyPoiRepository`, mirrors `supabase_property_amenity_repo.py`)
- `src/properties/adapters/inmemory/inmemory_property_poi_repo.py` — new
- `src/properties/application/use_cases/replace_property_pois.py` — new
- `src/properties/application/use_cases/update_property_poi.py` — new
- `src/properties/application/use_cases/delete_property_poi.py` — new
- `src/properties/application/use_cases/list_property_pois.py` — new
- `src/properties/adapters/api/schemas.py` — add `CreatePropertyPoiRequest`, `ReplacePropertyPoisRequest`, `UpdatePropertyPoiRequest`, `PropertyPoiResponse`
- `src/properties/adapters/api/routes/property_pois.py` — new router with four handlers
- `src/properties/container.py` — add `property_poi_repo: PropertyPoiRepository | None = None` constructor arg + conditional wiring of the four use cases
- `src/shared/entrypoints/bootstrap.py:get_property_container` — instantiate `SupabasePropertyPoiRepository(client)` and pass to container
- `src/shared/main.py` — `app.include_router(property_pois.router, prefix="/api/v1/admin")`
- `alembic/versions/<auto>_add_property_pois_table.py` — migration per ADR §6.1
- `tests/conftest.py` — add `property_poi_repo` fixture; extend `property_container` to receive it
- `tests/database/test_migration.py` — update `test_current_revision_is_head` to assert the new head (replaces the current `p2q3r4s5t6u7` assertion). The test exists to catch un-applied migrations; bumping it is normal hygiene whenever a migration lands.
- Tests:
  - `tests/unit/properties/test_replace_property_pois_use_case.py` — replace-all semantics, manually_edited flag, cross-org guard, aggregate_version bumped
  - `tests/unit/properties/test_update_property_poi_use_case.py` — PATCH semantics, partial fields, cross-property defense
  - `tests/unit/properties/test_delete_property_poi_use_case.py` — happy path, missing id, cross-property defense, aggregate_version bumped
  - `tests/unit/properties/test_list_property_pois_use_case.py` — happy path, empty, cross-org guard
  - `tests/integration/test_property_pois.py` — create file. `TestPropertyPois` class. 200 happy paths for all four endpoints, 404 cross-property, 403 cross-org, 401 no auth, 422 invalid body (negative distance, lat>90, missing required fields). Mirror `tests/integration/test_property_owners.py` structure.
- Docs: update `docs/features/properties.md` — add four new use cases to the catalog table and a `### Property POIs` subsection. Note ADR-010 is the source of architectural truth.

## Acceptance criteria

**Integration-level (FastAPI + in-memory adapters via the existing `property_container` fixture):**

- [ ] `POST /api/v1/admin/properties/{id}/pois` with a 3-element `pois` body returns `200` with all 3 rows, each with a generated `id`, `manually_edited=true`, and `created_at`/`updated_at` populated.
- [ ] `POST /pois` replaces — calling it twice on the same property leaves only the second call's rows. The first call's POI ids are gone.
- [ ] `POST /pois` with `metadata={"school_type": "public", "rating": 4.2}` round-trips the dict on `GET /pois`.
- [ ] `GET /api/v1/admin/properties/{id}/pois` returns the property's POIs sorted predictably (by `created_at desc` is fine — flag if product wants something else).
- [ ] `PATCH /pois/{poi_id}` with `{"distance_meters": 320}` updates only that field; `category`, `name`, `latitude`, `longitude` are unchanged. `manually_edited` is set to `true` on the response.
- [ ] `DELETE /pois/{poi_id}` returns `204` and the POI is gone from `GET /pois`.
- [ ] All four routes return `403` when called with `organization_id` of an org the caller is not a member of (raised by `require_org_member` middleware).
- [ ] All four routes return `404` when called with a `property_id` that doesn't exist.
- [ ] All four routes return `404` when `property_id` exists but belongs to a different organization than the `organization_id` query param (caller is a legitimate member of the queried org, but the property they're addressing isn't theirs — raised by the inline org-scope check in the use case).
- [ ] `PATCH /pois/{poi_id}` and `DELETE /pois/{poi_id}` return `404` when the `poi_id` exists but belongs to a different property than the URL's `property_id`.
- [ ] No-auth requests return `401`.
- [ ] Invalid body returns `422` (negative `distance_meters`, `latitude > 90`, empty `name`, `pois` list longer than 200).
- [ ] `POST /pois` with `pois: []` returns `200` with `[]`, the property's POI catalog is cleared on subsequent `GET`, and `aggregate_version` is incremented.
- [ ] `PATCH /pois/{poi_id}` with `metadata={"new_key": "value"}` round-trips the dict on `GET /pois`.
- [ ] After `POST`, `PATCH`, or `DELETE`, the property's `aggregate_version` is incremented (verified via repo state).

**Unit-level (against in-memory adapter):**

- [ ] `ReplacePropertyPois.execute` calls `repo.replace_for_property` exactly once with the input list, all rows flagged `manually_edited=true`. Returns the persisted list.
- [ ] `UpdatePropertyPoi.execute` raises `PropertyNotFoundError` when the POI's `property_id` doesn't match the `property_id` argument (verified via tracking-repo subclass that records calls — the repo's `update` method is never reached).
- [ ] `DeletePropertyPoi.execute` raises `PropertyNotFoundError` when the POI doesn't exist (no idempotent-delete behavior — matches the `delete_property` precedent in the codebase). Also raises `PropertyNotFoundError` when the property doesn't exist.
- [ ] `ListPropertyPois.execute` returns `[]` for a property with no POIs.
- [ ] All four use cases short-circuit on cross-org property access — verified via tracking-repo recording zero writes when `prop.organization_id != organization_id`.

**Regression:**

- [ ] All 474 existing tests still green. The new `property_poi_repo` fixture wires additively; nothing breaks.
- [ ] The existing `property-amenities` surface (`property_amenities` table, `DiscoverPropertyAmenities` use case, `POST /property-amenities/discover`) is untouched.

## Open questions

- **Auth tier — any-member vs OWNER/ADMIN?** Defaulting to `require_org_member` (any member can edit POIs). If product wants OWNER/ADMIN-only (matches `delete_property` and `publish_property`), add the role check in the route. Not blocking.
- **Sort order on GET.** `created_at desc` proposed. Could be `(category, distance_meters asc)` if that matches the dashboard render. Confirm before merge.
- **Maximum POIs per replace?** Spec commits to `Field(max_length=200)` on the `pois` list (see §6 schema). 200 is generous — far above the ~18 categories × 5 top-N from the auto-discovery spec. Flag if product wants a different ceiling.

## Resolved during sharpening (assumptions, not questions)

- **`metadata` dict is untyped.** Pydantic `dict` with no schema. Provider-specific extras (Google rating, OSM tags) and agent notes coexist without us pre-defining the keys.
- **POST is replace, not upsert/append.** Matches user's stated preference in ADR v4. Agents who want to add one POI without re-submitting use the (later-added or out-of-scope) per-row POST. v4-v7 don't currently spec a "create one POI" endpoint; if needed, add `POST /pois/single` as a follow-up.
- **No cost-score column on `property_listings` in this spec.** Migration 2 from ADR §6.2 lands with the cost-of-life spec.
- **No configurable_settings table in this spec.** Migration 3 lands with the workflow spec.

## Out of scope follow-ups

This spec is the foundation slice of ADR-010's implementation. Three follow-up specs land next:

- **`2026-05-property-poi-discovery-workflow.md`** — `POST /properties/{id}/enrich` command endpoint, `ENRICH_PROPERTY_REQUESTED.v1` command, `property-enrichment-queue` + DLQ, `properties.entrypoints.enrichment_worker`, `EnrichProperty` orchestrator (stages 1+2), multi-provider `PlacesService` factory + `OverpassPlacesService` adapter, geo-cache decorator, `_AppConstants` + `configurable_settings` table.
- **`2026-05-property-cost-of-life.md`** — stage 3 (`CostOfLifeService`), `CostScore` + `HouseholdComposition` domain models, `ListingDerivedSignalsRepository` cross-context port (in listings) + SQLAlchemy adapter, `property_listings` enrichment columns migration (ADR §6.2), `PATCH /listings/properties/{id}` cost-score override endpoint.
- **`2026-XX-property-poi-embedding.md`** (deferred per ADR v8) — `EmbeddingProvider` + OpenAI adapter, `EmbeddingRepository` + Pinecone adapter, stage 4 in the orchestrator. Lands when product confirms semantic search ships.

Other follow-ups not strictly part of the ADR-010 arc:

- "Create one POI" endpoint (`POST /pois/single`) if the replace-all model is too coarse for some agent workflows.
- POI dedup tooling (find listings with duplicate place_ids) — useful once the auto-discovery worker is live and the catalog grows.

## Commits

Per `_TEMPLATE.md` § Commits — `feat(properties)` for the use case + route + repo + schema:

`feat(properties): manual POI catalog endpoints + PropertyPoi domain`

Plus a follow-up `docs(properties)` if the README/feature doc grows beyond a one-line update.
