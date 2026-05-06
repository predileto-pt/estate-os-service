# Admin org-scoped active listings endpoint

**Status:** shipped
**Owner:** Peter
**Created:** 2026-05-05
**Shipped:** 2026-05-06 (474 tests green; 12 new — 4 unit, 8 HTTP integration. Plus the prerequisite `listing_repo` / `listing_container` conftest fixtures that the codebase had been missing.)

## Problem

There is no authenticated, org-scoped way for an agent to see *just* their organization's currently-published listings. Today the choices are:

- **Public listings endpoint** — `GET /api/v1/listings/properties` (`src/listings/adapters/api/routes/listings.py:83-122`). No auth, returns every `ACTIVE` row across **all** orgs. An agency client can't filter to "my listings" without leaking other orgs' rows over the wire and post-filtering, which is unacceptable for a multi-tenant admin UI.
- **Admin properties endpoint** — `GET /api/v1/admin/properties?organization_id=<uuid>` (`src/properties/adapters/api/routes/properties.py:147-164`) routes through `ListProperties` (`src/properties/application/use_cases/list_properties.py`). Returns **all** statuses for the org (DRAFT, WITHDRAWN, SOLD, RENTED, ACTIVE — same shape as the editor view). It's the wrong lens for "what's live right now."
- **Admin properties active variant** — `GET /api/v1/admin/properties/active` (`src/properties/adapters/api/routes/properties.py:108-120`) is global and unauthenticated; it powers the public site preview, not an admin view.

The agencies-dashboard needs a "my live listings" screen — an authenticated, org-scoped query that returns the same projection shape the public portal serves (so the dashboard mirrors what visitors see), with a permission check that blocks cross-org access.

## Goal

Org members can fetch their organization's active listings via:

```
GET /api/v1/admin/listings/properties?organization_id=<uuid>
```

The response is identical in shape to the public `GET /api/v1/listings/properties` (so dashboard code can render the same card component), filtered to rows where `organization_id = <uuid>` AND `status = ACTIVE`. Auth is enforced via the existing `require_org_member` dependency: non-authenticated callers get 401, authenticated callers who aren't members of `<uuid>` get 403, members of the org get 200 with their rows.

## Non-goals

- **Filtering by status (DRAFT, WITHDRAWN, SOLD, RENTED).** This spec is "active only." A separate "all my listings" admin view would belong on the *properties* context (write-side), not the *listings* projection — and is its own spec.
- **Search / typology / price / district filters.** The active spec `listings-cursor-pagination-and-filters` already covers filtering for the public endpoint; once it lands we'll mirror the patterns here. For now, a flat list per org keeps the surface area small.
- **Cursor pagination.** Same — covered by the pagination spec. This endpoint introduces a simple `limit`/`offset` matching the public endpoint's existing parameters; we'll cut over to cursors when that spec ships.
- **A new domain context, read model, or response shape.** Reuse `ListingRepository` / `ListedProperty` / `ListedPropertyResponse`. Symmetry with the public endpoint is the whole point.
- **Cross-org / super-admin views.** Strictly per-organization — the route gates on `require_org_member`.
- **Owner / contact data exposure.** The public endpoint already strips owners; admin gets the same shape. If admin needs owners later, that's a different field set and a different endpoint.
- **Reading from the `property_listings` projection.** The public endpoint reads from the write-side `properties` / `property_prices` / `property_images` tables via `SqlAlchemyListingRepository`. We mirror that exact path so admin and public stay byte-identical. Migrating either to the projection is a separate decision (and would belong in the redis-cache or pagination spec).

## Approach

### 1. Repository port: extend `ListingRepository`

Add two new methods on the existing port at `src/listings/application/ports/listing_repository.py:20`:

```python
@abstractmethod
async def list_active_for_organization(
    self, organization_id: UUID, filters: PropertyFilters
) -> list[ListedProperty]: ...

@abstractmethod
async def count_active_for_organization(
    self, organization_id: UUID, filters: PropertyFilters
) -> int: ...
```

Reuses `PropertyFilters` (line 10) so the limit/offset plumbing is identical to the public path. The new methods do not accept a global "all orgs" mode — the org scope is the whole point. The existing `list_active` / `count_active` (used by the public endpoint) stay untouched.

### 2. Repository adapters: implement filter

**`src/listings/adapters/database/listing_repository.py`** — add the org filter into `_build_query` via a private overload, or duplicate the small query body. Per-method session scope (recently-shipped pattern) stays:

```python
async def list_active_for_organization(
    self, organization_id: UUID, filters: PropertyFilters
) -> list[ListedProperty]:
    """Return ACTIVE listings for one organization. The `WHERE status = ACTIVE`
    predicate comes from `_build_query` and is the canonical enforcement
    of status filtering — the in-memory adapter does NOT honor this
    (`ListedProperty` carries no `status` field) and is unsuitable for
    status-exclusion testing.
    """
    async with self._session_factory() as session:
        query = self._build_query(filters)
        query = query.where(ReadPropertyModel.organization_id == str(organization_id))
        query = query.order_by(ReadPropertyModel.updated_at.desc())
        query = query.limit(filters.limit).offset(filters.offset)
        ...  # same _load_prices / _load_images / _matches_price_filter / _to_domain dance
```

`count_active_for_organization` mirrors `count_active` with the extra `organization_id` predicate.

**In-memory adapter** at `src/listings/adapters/inmemory/inmemory_listing_repository.py` — add a list-comprehension variant that filters by `organization_id`. Status filtering is **not** added: `ListedProperty` has no `status` field, the existing in-memory `list_active` returns every row in `_properties` regardless of status, and we deliberately don't widen the domain model in this spec. Tests that need status discrimination must seed only ACTIVE-shaped rows.

### 3. Use case: `ListOrgActiveListings`

New file `src/listings/application/use_cases/list_org_active_listings.py`:

```python
class ListOrgActiveListings:
    def __init__(self, listing_repo: ListingRepository) -> None:
        self.listing_repo = listing_repo

    async def execute(
        self, *, organization_id: UUID, filters: PropertyFilters
    ) -> tuple[list[ListedProperty], int]:
        properties = await self.listing_repo.list_active_for_organization(
            organization_id, filters
        )
        total = await self.listing_repo.count_active_for_organization(
            organization_id, filters
        )
        return properties, total
```

Same shape as `ListProperties` (the public-endpoint use case at `src/listings/application/use_cases/list_properties.py`), just with an extra `organization_id` parameter threaded through. **No permission check at the use case** — the route's `require_org_member` is the gate.

### 4. HTTP route

Add to `src/listings/adapters/api/routes/listings.py` directly above the existing public `list_properties` handler. Mounts under the **admin** prefix (see §6 for routing — the existing `listings.router` is already mounted at `/api/v1/listings` for public; we mount the same router *also* at `/api/v1/admin/listings`, OR introduce a sibling router. Decision: sibling router for clean separation — see §6).

```python
@admin_router.get(
    "/properties",
    response_model=PaginatedListingResponse,
    summary="List active listings for the caller's organization (admin view)",
    responses={
        200: {"description": "Active listings for the organization"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not a member of this organization"},
    },
)
async def list_org_active_listings(
    organization_id: UUID,
    request: Request,
    listing_type: ListingType | None = Query(None),
    typology: Typology | None = Query(None),
    min_price: Decimal | None = Query(None, ge=0),
    max_price: Decimal | None = Query(None, ge=0),
    district: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _member: tuple[User, Membership] = Depends(require_org_member),
) -> PaginatedListingResponse:
    container = request.app.state.listing_container
    filters = PropertyFilters(
        listing_type=listing_type, typology=typology,
        min_price=min_price, max_price=max_price, district=district,
        limit=limit, offset=offset,
    )
    properties, total = await container.list_org_active_listings.execute(
        organization_id=organization_id, filters=filters,
    )
    items = [_to_response(p, await _generate_image_urls(request, p)) for p in properties]
    return PaginatedListingResponse(items=items, total=total, limit=limit, offset=offset)
```

The `_member` parameter is intentionally unused in the body — `Depends(require_org_member)` runs for its side-effect (the auth check). FastAPI invokes it before the handler, raising 401/403 from inside the dependency itself. The handler body only runs on a successful auth.

**Net-new imports in `listings.py`:** `User` (`identity.domain.models.user`), `Membership` (`organizations.domain.models.membership`), `require_org_member` (`shared.api.dependencies`), and `Depends` (`fastapi`) are not currently imported in `src/listings/adapters/api/routes/listings.py` — the public route doesn't need them. The admin route adds all four.

`require_org_member` (`src/shared/api/dependencies.py:64`) reads the JWT-derived user + memberships off `request.state` (populated by the identity middleware) and:

- Raises `401` if no auth token / `request.state.user` is missing.
- Raises `403` if the caller is authenticated but no membership row matches `organization_id`.

So 401 / 403 happen *before* the handler body runs. The use case never sees an unauthorized call.

### 5. Container wiring

`src/listings/container.py` — add `list_org_active_listings`:

```python
self.list_org_active_listings = ListOrgActiveListings(listing_repo=listing_repo)
```

The container is process-scoped — `get_listing_container()` (`src/shared/entrypoints/bootstrap.py:261`) caches a single instance and stores it on `app.state.listing_container` during lifespan. The new admin route reads the **same** `request.app.state.listing_container` as the public route. No second container, no second mount in `app.state`, no separate session factory — both routes share one container with the new use case wired into it.

### 6. Routing — sibling admin router

`src/listings/adapters/api/routes/listings.py` currently exposes one `router = APIRouter(tags=["property-listings"])` mounted at `/api/v1/listings` in `src/shared/main.py:206`. Two options for the new admin route:

- **Option A — same router, same prefix.** Add the handler to `router`, mount the same router twice (once under `/api/v1/listings` for public, once under `/api/v1/admin/listings` for admin). Cleanest reuse but conflates the two surfaces — every public route would silently appear under `/admin/listings/...` too.
- **Option B — same router, per-route auth (matches `properties.py`).** Add the new admin handler to the existing `router` with `Depends(require_org_member)` directly on the handler signature. The router is mounted once at `/api/v1/listings`, and the admin route lives at `/api/v1/listings/admin/properties` (or similar) — auth is the only thing that distinguishes admin from public. This is the precedent `src/properties/adapters/api/routes/properties.py` actually uses (one router, per-route `Depends`).
- **Option C — sibling router (chosen).** Introduce `admin_router = APIRouter(tags=["property-listings-admin"])` in the same file. Mount it in `src/shared/main.py` under `/api/v1/admin/listings` next to the public mount at `/api/v1/listings`.

Option C is a new pattern for this codebase — picked deliberately over the `properties.py` precedent (Option B) because the URL prefix should signal authority: `/api/v1/admin/...` paths are the existing admin surface (`admin/properties`, `admin/property-owners`, `admin/property-images`, …), and listings should match that convention. Mixing public and admin routes under the same `/api/v1/listings` prefix would break the URL-as-policy signal that the rest of the API already communicates. One file, two `APIRouter` instances, two `include_router` calls. Container is shared (see §5) — no extra plumbing.

### 7. Response shape

Reuse the existing `PaginatedListingResponse` and `ListedPropertyResponse` from `src/listings/adapters/api/schemas.py`. Same fields the public endpoint exposes. The admin doesn't get extra columns here — if a richer admin shape (status, version, enrichment timestamps) is wanted later, that's its own spec.

## Affected files / surfaces

- `src/listings/application/ports/listing_repository.py` — add `list_active_for_organization` and `count_active_for_organization` abstract methods
- `src/listings/adapters/database/listing_repository.py` — implement both methods (per-method session scope, identical to existing methods)
- `src/listings/adapters/inmemory/inmemory_listing_repository.py` — implement both methods
- `src/listings/application/use_cases/list_org_active_listings.py` — new use case
- `src/listings/container.py` — wire `list_org_active_listings`
- `src/listings/adapters/api/routes/listings.py` — add `admin_router` with the new handler
- `src/shared/main.py` — `app.include_router(listings.admin_router, prefix="/api/v1/admin/listings")` next to the existing public mount at line 206
- `tests/conftest.py` — new `listing_repo` and `listing_container` fixtures; extend the `app` fixture to inject `listing_container=listing_container`
- Tests (existing flat layout — no new subfolders):

  **Test infrastructure (prerequisite — must land in this PR):**

  No `listing_container` test fixture exists today. `tests/conftest.py:258-265`'s `app` fixture wires `container`, `identity_container`, `billing_container`, `property_container` — and **not** `listing_container`. Any test that hits `/api/v1/listings/...` or the new `/api/v1/admin/listings/...` would fail with `AttributeError: 'State' object has no attribute 'listing_container'` because the lifespan-bootstrap path is skipped whenever a container is injected. To unblock this spec's integration tests (and the future `listings-cursor-pagination-and-filters` work):

  - **Add a `listing_container` fixture in `tests/conftest.py`.** Builds `ListingContainer(listing_repo=InMemoryListingRepository(), property_listing_repo=InMemoryPropertyListingRepository(), address_parser=<inmemory>)`. There is already an in-memory address parser at `src/listings/adapters/inmemory/inmemory_address_parser.py` — reuse it.
  - **Extend the `app` fixture call** to pass `listing_container=listing_container` to `create_app(...)`. `create_app` already accepts the kwarg (`src/shared/main.py:61`) and sets it on `app.state.listing_container` (`src/shared/main.py:240-241`).
  - **Add a `listing_repo` fixture** that returns the same `InMemoryListingRepository` instance the container is built from, so tests can seed it directly.

  **Unit test:**

  - `tests/unit/listings/test_list_org_active_listings_use_case.py` — happy path, empty org, repo invoked with the right `organization_id` + `filters` (assert on tracking-repo subclass), two-org seeding asserts org-scope correctness. **Status-exclusion is not asserted at unit level** for the reason explained in §2 (no `status` field on `ListedProperty`, no in-memory filter).

  **Integration test:**

  - `tests/integration/test_listings.py` — **create this file** (it does not exist; only `tests/unit/listings/test_inmemory_property_listing_repo.py` exists). Add a `TestAdminOrgActiveListings` class mirroring `TestPublishProperty`'s shape from `tests/integration/test_properties.py:402`. Use the new `listing_repo` fixture (NOT `property_repo` — the listings endpoint reads via the listings adapter, not the properties adapter; seeding `property_repo` would put rows in the wrong place). For row-construction helpers, copy or reference `_make_property` / `_make_publishable_property` from `tests/integration/test_properties.py:324,343` — they're file-private helpers, not conftest fixtures, so the implementer either copies them, adapts them to produce `ListedProperty` instances, or refactors them up to conftest. Either works; copying is simplest given `ListedProperty` differs from `Property` (no owners, no status). Cover:
    - 200 happy path returns only the calling org's rows.
    - Cross-org isolation (seed rows for `OTHER_ORGANIZATION_ID`, assert they're not in the response).
    - 403 on call with `organization_id=OTHER_ORGANIZATION_ID` (caller is a member of `TEST_ORGANIZATION_ID` only).
    - 401 on no auth.
    - Empty `[]` for an org with no active listings.
    - Pagination params honored (`limit`, `offset`).

  Status-exclusion is **explicitly not in the test plan** — see Acceptance criteria for the rationale. The SQL `WHERE status = ACTIVE` predicate is documented on the SQLAlchemy adapter method's docstring (§2) and is the canonical enforcement; the test suite trusts it.
- Docs: update `docs/features/listings.md` — add the admin endpoint to the catalog and a one-paragraph "Admin org-scoped view" subsection under the existing endpoint write-up.

## Acceptance criteria

**Integration-level (FastAPI + in-memory adapters via the new `listing_container` fixture):**

- [ ] `GET /api/v1/admin/listings/properties?organization_id=<uuid>` with a valid auth token returns `200` with a `PaginatedListingResponse` containing the org's seeded rows.
- [ ] No auth → `401` (raised by `require_org_member` before the handler body).
- [ ] Authenticated but not a member of `organization_id` → `403` (raised by `require_org_member`).
- [ ] Org with no rows → `200` with `items: []`, `total: 0`.
- [ ] Other orgs' rows are not included even when they share filter values.
- [ ] Response shape matches `GET /api/v1/listings/properties` field-for-field (same `PaginatedListingResponse` / `ListedPropertyResponse`).
- [ ] `limit` / `offset` query params behave identically to the public endpoint (defaults 20 / 0; bounded 1-100); `limit=200` returns `422` from Pydantic validation.
- [ ] Image `download_url` fields are populated via `_generate_image_urls`, same as the public endpoint.

**Unit-level (against in-memory adapter):**

- [ ] Use case asserts the repo is called with the exact `organization_id` and `filters` (verified via tracking-repo subclass).
- [ ] Empty repo → use case returns `([], 0)`.
- [ ] Two orgs in the in-memory repo, query for org A → use case returns only org A's rows.

**Status filtering — not in the test plan, enforced at the SQL layer:**

There is no AC asserting "DRAFT/WITHDRAWN/SOLD/RENTED rows excluded from the response" because the test suite runs against in-memory adapters, and `ListedProperty` has no `status` field for the in-memory adapter to filter on (see §2). The SQL `WHERE status = ACTIVE` predicate inside `_build_query` is the canonical enforcement; it's documented on `list_active_for_organization`'s docstring (§2). If a future ops requirement justifies real-DB integration tests for listings, that's a separate spec — possibly carrying `status` onto `ListedProperty` in the process.

**Regression:**

- [ ] All existing tests still green — the public `GET /api/v1/listings/properties` endpoint must not regress (same router file is being touched).
- [ ] The new `listing_container` and `listing_repo` conftest fixtures don't break unrelated tests (no test currently injects `listing_container`, so this should be additive only — verify by running the full suite).

## Open questions

- **Sort order:** the spec uses `ORDER BY updated_at DESC` (most-recently-touched first) on the assumption that "what's freshest" is the natural admin lens. Public endpoint sorts by `created_at DESC`. Confirm with product before merge — if they want consistency, switch to `created_at DESC` and note in the PR.

## Resolved during sharpening (assumptions, not questions)

- **Public route `organization_id` query param** — rejected. Public callers shouldn't be able to enumerate by org. Keeping the surfaces separate also means we can tighten admin without touching public.
- **Routing pattern** — sibling router (Option C in §6), mounted at `/api/v1/admin/listings`. Diverges from the `properties.py` precedent (one router, per-route auth) so the URL prefix matches the rest of the admin surface (`admin/properties`, `admin/property-owners`, …).
- **Status-exclusion is integration-only.** In-memory adapter cannot filter by status because `ListedProperty` carries no `status` field. ACs and tests are split accordingly.
- **Container is shared with the public route.** No second container, no second `app.state` field — `request.app.state.listing_container` serves both.
- **Status-exclusion is not asserted in tests.** The SQL `WHERE status = ACTIVE` predicate is canonical and documented on the SQLAlchemy adapter method's docstring; the in-memory adapter cannot filter on a field `ListedProperty` doesn't carry. Real-DB integration coverage of status filtering is a separate spec if/when needed.
- **`listing_container` test fixture.** This spec lands a prerequisite the codebase has been missing — without it, no integration test could hit any listings route. Future listings work (e.g. cursor-pagination spec) builds on top of it.

## Out of scope follow-ups

- Status filter for admin (`?status=draft`) — folds into a future "all my listings" view that reads write-side properties, not the listings projection.
- Cursor pagination — covered by the active `listings-cursor-pagination-and-filters` spec.
- Bulk actions on the result (multi-publish, multi-withdraw) — separate spec each.
- Admin-only enrichment fields (`location_enriched_at`, `location_enrichment_attempts`, `aggregate_version`) — only useful for ops dashboards; spec a separate `/admin/listings/diagnostics/...` endpoint if needed.

## Commits

Use conventional-commit style (`_TEMPLATE.md` § Commits). Likely one `feat(listings):` covering the use case + route + repo additions, with a follow-up `docs(listings):` if the README/feature doc grows beyond a one-line update. Example: `feat(listings): admin GET /admin/listings/properties scoped by organization_id`.
