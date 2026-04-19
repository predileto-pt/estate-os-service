# Identity bounded context + membership-derived admin authz

**Status:** in-progress
**Owner:** Peter
**Created:** 2026-04-18

## Problem

Two concrete, interlocking weaknesses in today's auth + tenancy model:

1. **Admin-vs-portal boundary is unenforced at the middleware layer.** `src/shared/api/middleware.py::JWTAuthMiddleware` accepts any valid Supabase token and sets `request.state.supabase_user_id` — it does not know or check whether the caller is an admin (someone with agency memberships) or a portal user (an applicant booking a viewing). The only thing stopping a portal token from hitting `/api/v1/admin/properties` today is that the business logic incidentally returns empty results. There is no deliberate 403. A single bug in a filter leaks admin data to portal callers.

2. **`customers` bounded context conflates Identity with Tenancy.** `src/customers/` currently owns both *who you are* (`User`, `PortalUser`, register/login) and *what you can do* (`Organization`, `Membership`, `Invitation`, `Subscription`, `Notification`). Two unrelated aggregate clusters under one context. Worse, `User.organization_id` is a 1:1 denormalised shortcut that breaks the moment a human needs to belong to more than one org (realistic for Portuguese real-estate: agents working at multiple agencies, franchise owners).

A third weakness — RLS is bypassed everywhere because `src/shared/entrypoints/bootstrap.py:90,111` uses `service_role_key` — is real and acknowledged but **deferred to the follow-up spec `admin-rls-phase-one`**. That work depends on three unresolved technical spikes (supabase-py JWT mechanics, SQLAlchemy `auth.uid()` via `SET LOCAL`, testcontainers strategy) and belongs in its own spec. This spec makes the structural moves — DDD split + membership-derived admin authz — that Spec B builds on.

At 100–1000 DAU — the target band — the two in-scope weaknesses compound. The fix is one spec because the DDD split and the membership-based authz share the same underlying move: make `Membership` the authoritative source of admin access, not `User.organization_id` or a JWT claim.

## Goal

Split `customers` into a DDD-aligned `identity` + `organizations` pair of bounded contexts, collapse `PortalUser` into `User`, and make `Membership` the single source of truth for admin access (derived at middleware time, not cached in a JWT claim) — so a portal token cannot reach an admin endpoint and the two aggregate clusters are cleanly separated.

## Non-goals

- **No RLS changes.** DB access stays on `service_role_key` with the existing app-layer `require_org_member` checks. RLS is the follow-up spec `admin-rls-phase-one`.
- **No per-request user-JWT Supabase clients.** Also part of the RLS follow-up.
- **No new deployable service.** `identity` is a new bounded context inside `estate-os-service`. Promotion to a standalone service stays on the shelf for the >1k DAU horizon.
- **No second Supabase project.** Single auth pool, same `auth.users` table. The admin/portal boundary is enforced at the application layer (via membership lookup), not cryptographically.
- **No `user_type` custom JWT claim.** The claim would be a cache of membership state, stale the moment a membership is revoked. Admin-ness is derived from the current DB state, not a JWT field.
- **No adapter consolidation.** Today every repo port has two adapters — `Supabase*Repository` (PostgREST, used in prod via `bootstrap.py`) and `SqlAlchemy*Repository` (used in tests). This spec preserves the dual-adapter pattern and mirrors it across identity + organizations (Q1 = A1.a). Consolidation is a follow-up.
- **No role-based admin capabilities.** `MembershipRole` (OWNER / ADMIN / MEMBER) already exists but is not used for authorisation decisions today. This spec keeps that as-is — "has any membership" means admin. Role-based authz is a follow-up.
- **No active-org JWT claim.** Frontend continues to pass `organization_id` explicitly on every admin call (the existing pattern with `require_org_member`). "Active org in JWT" is a nice-to-have for later.
- **No Lambda / edge-auth hooks.** We stay in-process in the FastAPI middleware layer.

## Approach

Two tracks, shipped as one release. Commits are ordered:

- **Commit 1** — Alembic baseline squash (see §Database migration). Pure infra move, no code changes.
- **Commit 2** — Mechanical `git mv src/customers/ src/organizations/` + import substitution with no content change. Keeps the review diff tractable (Q3 = 2-commit plan).
- **Commits 3–N** — Identity extraction, repo splits, middleware, `User.organization_id` drop, test rewiring. Each commit lands one coherent slice.

### Track 1 — DDD split: extract `identity`, rename `customers` → `organizations`

**New bounded context `src/identity/`.** Owns exactly one aggregate: `User(id, supabase_user_id, email, name, phone, google_metadata, created_at, updated_at)`. Note — **no `organization_id`**. Ports:

- `UserRepository` — CRUD for User.
- `UserLookupById` — **callable Protocol**, cross-context read port exposed to `organizations`:
  ```python
  class UserLookupById(Protocol):
      async def __call__(self, id: UUID) -> User | None: ...
  ```
  Bound at container-construction time to `FindUser.by_id`. Organizations calls `await self._user_lookup_by_id(id)`.
- `RegisterUserPort` — **callable Protocol**, cross-context write port exposed to `organizations.RegisterAdminAccount`:
  ```python
  class RegisterUserPort(Protocol):
      async def __call__(self, *, supabase_user_id: str, email: str, name: str, phone: PhoneNumber | None) -> User: ...
  ```
  Bound at container-construction time to `RegisterUser.execute`. Idempotent — returns the existing User on duplicate `supabase_user_id` (see Registration flow for why).

**Why callable Protocols (Q1 = 1.c).** Avoids the Protocol-method-name vs. use-case-method-name collision. The port is just a callable bound to a use-case method at DI time — no adapter class, no forced rename of use cases.

**Middleware lookup bypasses the Protocol surface (Q2 = 2.b).** Middleware lives in `src/shared/api/` — shared infrastructure, not a bounded context — so it may call use-case methods directly without a Protocol layer. Middleware uses `identity_container.find_user.by_supabase_id(sub)`. Only the cross-context organizations → identity dependency goes through callable Protocols.

Use cases:
- `RegisterUser` — `execute(...)` creates one User; idempotent on `supabase_user_id` (returns the existing row if the sub is already registered). Bound as the `RegisterUserPort` callable.
- `UpdateUserProfile` — `execute(user_id, name?, phone?)`.
- `FindUser` — two methods: `by_id(id: UUID)` (bound as the `UserLookupById` callable, used by organizations) and `by_supabase_id(supabase_user_id: str)` (used directly by middleware).

There is **no `GetUserProfile` use case** (Q2 = 2a) — the `/me` endpoint is a pure shaping function that reads `request.state` directly.

Adapters — dual (Q1 = A1.a):
- **PostgREST (prod)**: `src/identity/adapters/persistence/supabase_user_repo.py` (uses `supabase-py` AsyncClient)
- **SQLAlchemy (tests)**: `src/identity/adapters/database/user_repo.py` + SQLAlchemy model at `src/identity/adapters/database/models.py`
- **In-memory**: `src/identity/adapters/inmemory/inmemory_user_repo.py`

HTTP routes in `src/identity/adapters/api/routes/`:

- `portal_auth.py` — `POST /api/v1/portal/auth/register` (just creates a User)
- `me.py` — a single `GET /auth/me` handler mounted under both `/api/v1/admin` and `/api/v1/portal`, returning `{user: {...}, memberships: [{organization_id, role, organization_name, created_at}]}`. Handler reads `request.state.user` and `request.state.memberships` — no DB calls, no use case. Admin-prefix mount naturally 403s for a user without memberships via the middleware rule; portal-prefix mount returns `memberships: []` for pure portal users.
- `profile.py` — `PATCH /auth/profile` for profile updates (phone, name).

Container wires all of this.

**`PortalUser` collapses into `User`.** There is one `User` aggregate. Whether a user is an "admin" or a "portal" user is answered by querying their memberships, not by which table they live in. The system is not in production, so the migration just drops the `portal_users` table (no data preservation — see §Database migration).

**Rename `src/customers/` → `src/organizations/`.** Owns `Organization`, `Membership`, `Invitation`, `Subscription`, `Notification`. These are tenancy and commerce concerns, not identity. Its container wires organization/membership/invitation/subscription/notification repos + use cases. HTTP routes in `src/organizations/adapters/api/routes/`:

- `admin_auth.py` — `POST /api/v1/admin/auth/register` — the compound `RegisterAdminAccount` use case. See "Registration flow" below.
- `organizations.py`, `memberships.py`, `invitations.py`, `subscriptions.py`, `notifications.py`, `email.py` — unchanged in shape, renamed in path.
- `users.py` — deleted (was PortalUser-specific; `me.py` in identity supersedes it).

**Registration flow (Q #1 = 1c; Q3 transactional boundary = 3.a).** Two endpoints, two homes:

- `POST /api/v1/portal/auth/register` lives in `identity`. Calls `identity.RegisterUser.execute(supabase_user_id, email, name, phone)`. Creates one User row; idempotent on `supabase_user_id`. Returns `UserResponse`.
- `POST /api/v1/admin/auth/register` lives in `organizations`. Its handler invokes a `RegisterAdminAccount` use case that:
  1. Calls `identity.register_user` via the injected `RegisterUserPort` callable. Commits a User in its own identity-local transaction. **Idempotent** — a duplicate `supabase_user_id` returns the existing User without error.
  2. **Duplicate-account check.** Calls `organizations_container.membership_repo.list_by_user_id(user.id)`. If the user already has any memberships, returns **409** "admin account already exists" before step 3. Rules out (a) blind retries after a prior successful registration and (b) a portal user with prior membership bypassing the admin flow.
  3. Creates Organization + OwnerMembership + Subscription in a single `organizations`-local transaction.

  **Retry semantics.** If step 3 fails, the User row is **orphaned** but retryable: step 1 becomes a no-op on retry (returns the existing User), step 2 passes (the orphan still has no memberships), step 3 reruns. If the first full flow succeeded and the caller re-submits, step 2 sees the membership and returns 409 — no duplicate Org / Membership / Subscription created. Orphaned-row cleanup is a future operational concern, not a correctness issue at this scale.

  Returns `{user, organization, membership, subscription}`. Frontend contract matches today's admin register response.

**Cross-context dependency is one-way.** `organizations` depends on `identity` via the `UserLookupById` + `RegisterUserPort` callable Protocols — injected at container-construction time (Q1 = 1.c). `identity` does not import from `organizations`. Enforced by acceptance criterion `grep -rn "from organizations" src/identity/` → zero hits.

**Repository file split (Q7 = 7a, Q1 = A1.a).** Mirror the identity layout for organizations. Final tree:

```
src/identity/adapters/
  persistence/supabase_user_repo.py     # PostgREST (prod)
  database/user_repo.py                 # SQLAlchemy (tests)
  database/models.py                    # SQLAlchemy User model
  inmemory/inmemory_user_repo.py

src/organizations/adapters/
  persistence/
    supabase_organization_repo.py
    supabase_membership_repo.py
    supabase_invitation_repo.py
    supabase_subscription_repo.py
    supabase_notification_repo.py
  database/
    organization_repo.py
    membership_repo.py
    invitation_repo.py
    subscription_repo.py
    notification_repo.py
    models.py                           # SQLAlchemy models for 5 aggregates
  inmemory/ (unchanged file set, rehomed)
```

The `src/customers/adapters/database/repositories.py` 500-line monolith is split during the rename — each of the 5 org-side classes moves to its own file. `src/customers/adapters/database/models.py` is also split per aggregate. `SupabasePortalUserRepository` + `SqlAlchemyUser*` (for PortalUser) + the `PortalUser` SQLAlchemy model are all deleted.

### Track 2 — Dual-auth enforcement at middleware, `User.organization_id` dropped

**Middleware layering.** Keep `JWTAuthMiddleware` as the base (decode Supabase JWT → set `request.state.supabase_user_id`). Add a new `IdentityMiddleware` that runs after it, for every non-public request. Pseudocode:

```python
from starlette.middleware.base import BaseHTTPMiddleware

REGISTRATION_PATHS = {"/api/v1/admin/auth/register", "/api/v1/portal/auth/register"}

class IdentityMiddleware(BaseHTTPMiddleware):   # matches JWTAuthMiddleware (A6)
    async def dispatch(self, request, call_next):
        path = request.url.path
        if is_public(path):
            return await call_next(request)

        # Containers are attached to app.state at lifespan startup (A3).
        identity_container = request.app.state.identity_container
        organizations_container = request.app.state.organizations_container

        sub = request.state.supabase_user_id  # set by JWTAuthMiddleware
        if path in REGISTRATION_PATHS:
            # JWT is verified; the route handler creates the User row.
            return await call_next(request)

        user = await identity_container.find_user.by_supabase_id(sub)
        if not user:
            return Response(401, "Unknown user — registration required")
        request.state.user = user

        # Single JOIN query: memberships + organization_name projection (A5).
        # Avoids N+1 when /me renders membership lists.
        memberships = await organizations_container.membership_repo.list_by_user_id_with_org_names(
            user.id
        )
        request.state.memberships = memberships

        if path.startswith("/api/v1/admin/") and not memberships:
            return Response(403, "This account does not have admin access")

        return await call_next(request)
```

`list_by_user_id_with_org_names` returns a list of projections `{id, user_id, organization_id, role, organization_name, created_at, updated_at}` — a single SQL query with a JOIN against `organizations`. Shape in repo port: `MembershipWithOrgName` (dataclass projection type, not a domain aggregate).

**`require_org_member` dependency is simplified.** Today it does its own lookup. After this spec, it reads `request.state.memberships` and checks `any(m.organization_id == organization_id for m in memberships)`. Zero DB round-trips inside the dependency. A new `get_current_user` helper reads `request.state.user`.

**`REGISTRATION_PATHS` bypass (Q6 = 6a).** Hardcoded constant alongside `PUBLIC_PATHS`. Registration endpoints get JWT verification (caller proves Supabase identity) but skip the User-exists + membership-required checks (they're about to create the User). The handler uses `request.state.supabase_user_id` to know whose account it's creating.

**Drop `User.organization_id` (Q4 via not-in-prod).** System is pre-production; DB is throwaway. The migration drops the column with no back-fill logic. The two real consumers are rewritten:

- `src/customers/adapters/api/routes/subscriptions.py:60` (the `/subscriptions/current` endpoint) → at its new path in `organizations`, takes `organization_id` from the request, verifies membership via `require_org_member`, looks up the sub.
- `/me` returns `{user, memberships: [{organization_id, role, organization_name, created_at}]}`. **This is a breaking shape change** on the frontend-facing contract: today's response has `organization_id` inline on the user; tomorrow's has an explicit `memberships` array. Since the system isn't in production, this is a coordinated FE update in the same PR cycle.

### Database migration (Q5 = 5b)

**Alembic baseline squash.** Ships as Commit 1:

1. Delete every file under `alembic/versions/`.
2. Generate a single new baseline from the current (pre-split) SQLAlchemy models via `alembic revision --autogenerate -m "baseline"`.
3. Verify the baseline creates a DB schema byte-equivalent to the current schema by running it on a fresh Postgres container, dumping both with `pg_dump --schema-only --no-owner --no-privileges`, and asserting an empty diff.
4. Stamp dev DBs: drop-and-recreate (not-in-prod).

**Identity-split migration.** One new Alembic revision on top of the baseline (lands in Commit 3+ — any commit in the identity extraction sequence; Alembic ordering doesn't need to match git ordering):

1. `ALTER TABLE users DROP COLUMN organization_id;` (autogenerate handles FK + index cleanup).
2. `DROP TABLE portal_users;` — after the identity split, no code references it.
3. No back-fill. No membership inserts.
4. No table renames — Python packages change, DB tables stay named as they are (`organizations`, `memberships`, etc.).

**Downgrade path:** symmetrical reversal — recreate `portal_users`, re-add `users.organization_id`. Not exercised (dev DBs are nuked on rollback); included for Alembic completeness.

### Approach summary diagram

```
┌──────────────── FastAPI ──────────────────────────────────┐
│                                                            │
│  JWTAuthMiddleware → IdentityMiddleware                    │
│  decodes Supabase    reads containers from app.state       │
│  JWT, sets sub       if path in REGISTRATION_PATHS: skip   │
│                      else:                                 │
│                        user = identity.find_by_sub(sub)    │
│                        memberships = orgs.list_with_names  │
│                           (single JOIN — no N+1)           │
│                        if /admin/* and !memberships: 403   │
│                        attach user + memberships to state  │
│                                                            │
│  Admin route → reads request.state.{user, memberships}     │
│                business logic uses app.state.*_container   │
│                (service_role_key — same as today)          │
│                                                            │
│  Portal route → reads request.state.{user, memberships}    │
│                 same container pattern                     │
│                                                            │
│  Worker entrypoint → singleton_container (service_role)    │
└────────────────────────────────────────────────────────────┘
```

## Affected files / surfaces

### New files

**Identity context:**
- `src/identity/domain/models/user.py` — `User` dataclass (no `organization_id`)
- `src/identity/domain/exceptions.py` — `UserAlreadyExistsError`, `UserNotFoundError`, `DomainError` base (moved from customers)
- `src/identity/domain/value_objects.py` — `PhoneNumber` (only User uses it)
- `src/identity/application/ports/repositories/user_repository.py`
- `src/identity/application/ports/user_lookup.py` — **callable Protocol** `UserLookupById(Protocol): async def __call__(self, id: UUID) -> User | None`. Consumed by organizations; bound at DI time to `FindUser.by_id` (Q1 = 1.c).
- `src/identity/application/ports/register_user_port.py` — **callable Protocol** `RegisterUserPort(Protocol): async def __call__(self, *, supabase_user_id, email, name, phone) -> User`. Consumed by `organizations.RegisterAdminAccount`; bound at DI time to `RegisterUser.execute`.
- `src/identity/application/use_cases/register_user.py` — `execute()` creates one User, **idempotent on `supabase_user_id`** (returns existing row on duplicate sub). Bound as the `RegisterUserPort` callable.
- `src/identity/application/use_cases/update_user_profile.py`
- `src/identity/application/use_cases/find_user.py` — two methods: `by_id(id)` (bound as `UserLookupById`, used by organizations) and `by_supabase_id(supabase_user_id)` (used directly by middleware per Q2 = 2.b; no Protocol layer).
- `src/identity/adapters/api/routes/portal_auth.py` — `POST /auth/register` (portal-prefix only)
- `src/identity/adapters/api/routes/me.py` — `GET /auth/me` (mounted under both admin + portal); reads `request.state` only, no use case
- `src/identity/adapters/api/routes/profile.py` — `PATCH /auth/profile`
- `src/identity/adapters/api/schemas.py` — Pydantic shapes: `UserResponse`, `RegisterRequest`, `UpdateProfileRequest`, `MeResponse` (with memberships array)
- `src/identity/adapters/persistence/supabase_user_repo.py` — PostgREST adapter (prod)
- `src/identity/adapters/database/user_repo.py` — SQLAlchemy adapter (tests)
- `src/identity/adapters/database/models.py` — SQLAlchemy `User` model
- `src/identity/adapters/inmemory/inmemory_user_repo.py`
- `src/identity/container.py`

**Organizations additions (on top of the rename):**
- `src/organizations/application/use_cases/register_admin_account.py` — compound: (1) calls `identity.register_user` via `RegisterUserPort` (identity-local tx, idempotent), (2) creates Org + OwnerMembership + Subscription in a single `organizations`-local transaction. See Registration flow in Approach for retry semantics on step-2 failure.
- `src/organizations/adapters/api/routes/admin_auth.py` — `POST /auth/register` (admin-prefix only)
- `src/organizations/domain/value_objects.py` — `Address` (unused by User; stays with tenancy)
- `src/organizations/domain/exceptions.py` — all non-User exceptions (`OrganizationNotFoundError`, `SubscriptionNotFoundError`, `InvitationNotFoundError`, `InvitationExpiredError`, `AuthorizationError`, `Membership*`, etc.) + `DomainError` base (duplicated with identity; trivial)

**Shared:**
- `src/shared/database/engine.py` — async SQLAlchemy engine + session factory. Moved from `src/customers/adapters/database/engine.py`; both identity and organizations import from here.

**Middleware:**
- `src/shared/api/middleware.py` — add `IdentityMiddleware(BaseHTTPMiddleware)` class alongside existing `JWTAuthMiddleware`; add `REGISTRATION_PATHS` constant

**Migrations:**
- `alembic/versions/<stamp>_baseline.py` — squashed baseline (Q5 = 5b)
- `alembic/versions/<stamp>_identity_split.py` — the schema delta for this spec

### Renamed / updated

- `src/customers/` → `src/organizations/` — full rename of the package directory via `git mv` (Commit 2). Within it, after the rename:
  - Delete `src/organizations/domain/models/user.py` (moved to identity)
  - Delete `src/organizations/domain/models/portal_user.py` (collapsed into User)
  - `src/organizations/domain/models/authorization.py` — stays (it's about `MembershipRole` permissions)
  - `src/organizations/domain/models/value_objects.py` — deleted; `PhoneNumber` moves to identity, `Address` moves to `organizations/domain/value_objects.py` (note: path changes from `domain/models/value_objects.py` to `domain/value_objects.py` to match identity's layout)
  - `src/organizations/domain/exceptions.py` — stripped to non-User exceptions; `UserNotFoundError` / `UserAlreadyExistsError` extracted to identity; `PortalUser*` deleted
  - Delete `src/organizations/application/use_cases/register_user.py` (replaced by `register_admin_account.py`; user-creation half moves to identity)
  - Delete `src/organizations/application/use_cases/register_portal_user.py` (collapsed — portal registration now calls `identity.register_user` directly)
  - Delete `src/organizations/application/use_cases/get_portal_user.py`, `get_user_profile.py`, `update_user_profile.py` (moved to identity)
  - Delete `src/organizations/application/ports/repositories/user_repository.py`, `portal_user_repository.py` (moved)
  - Delete `src/organizations/adapters/persistence/supabase_user_repo.py`, `supabase_portal_user_repo.py`
  - Delete `src/organizations/adapters/inmemory/inmemory_user_repo.py`, `inmemory_portal_user_repo.py`
  - Delete `src/organizations/adapters/api/routes/auth.py` (split: admin half → `admin_auth.py` in organizations; portal half → `portal_auth.py` in identity)
  - Delete `src/organizations/adapters/api/routes/portal_auth.py`, `users.py`
  - **Split** `src/organizations/adapters/database/repositories.py` (500 lines) into 5 per-aggregate files — `organization_repo.py`, `membership_repo.py`, `invitation_repo.py`, `subscription_repo.py`, `notification_repo.py` (Q7 = 7a). Delete `SqlAlchemyUserRepository` from this file (moves to identity).
  - **Split** `src/organizations/adapters/database/models.py` into per-aggregate model files; delete the `User` + `PortalUser` SQLAlchemy models (User moves to identity, PortalUser deleted entirely)
  - `src/organizations/adapters/database/engine.py` — deleted (moved to `shared/database/engine.py`)
  - `src/organizations/adapters/api/schemas.py` — stripped to non-User schemas (`OrganizationResponse`, `MembershipResponse`, `InvitationResponse`, `SubscriptionResponse`, `NotificationResponse`). User/Portal/Register schemas extracted to identity.
  - `src/organizations/container.py` — **deleted**; replaced by new `organizations/container.py` written from scratch with clean wiring. Drops user-related wiring; accepts `UserLookupById` + `RegisterUserPort` callables from the identity container at construction.
  - `src/organizations/application/services/authorization.py` (if present) — stays; uses `MembershipRole` permissions from `authorization.py` model

- `src/customers/container.py` — **deleted** (replaced by new `src/identity/container.py` + `src/organizations/container.py`)
- `src/shared/api/middleware.py` — existing `JWTAuthMiddleware` stays; add `IdentityMiddleware(BaseHTTPMiddleware)`; wire ordering in `main.py` so identity runs after JWT
- `src/shared/api/dependencies.py` — `require_org_member` reads from `request.state.memberships` (zero DB hits); `get_current_user` (new helper) reads `request.state.user`. Imports change from `customers.domain.models.user` / `.membership` to `identity.domain.models.user` / `organizations.domain.models.membership`.
- `src/shared/entrypoints/bootstrap.py` — split `get_container()` into `get_identity_container()` + `get_organizations_container()`. Worker container factories unchanged (all still service_role). Nine `from customers.*` imports retargeted.
- `src/shared/main.py` — wiring change: `app.state.identity_container`, `app.state.organizations_container`; add `IdentityMiddleware`; one `from customers.*` import retargeted.
- **Cross-context `User` / `Membership` imports — 9 non-customers files** (grep-verified):
  - `src/shared/api/dependencies.py` (2 imports: `User`, `Membership`)
  - `src/shared/main.py` (1 import)
  - `src/shared/entrypoints/bootstrap.py` (9 imports)
  - `src/properties/adapters/api/routes/{properties,property_owners,extraction_jobs,property_amenities,property_prices,property_images}.py` (2 imports each)
- Documentation:
  - Delete `docs/features/customers.md`; add `docs/features/identity.md` + `docs/features/organizations.md`
  - Update `docs/features/README.md` — context table and cross-context diagram
  - Update `README.md` — bounded-contexts table (from 6 contexts to 7: identity + organizations + properties + screening + bookings + contract_intelligence + listings)
  - **Rewrite `CLAUDE.md`'s "Two Bounded Contexts" section** — already stale (there are 6 today, becoming 7). Proper rewrite to list all 7 contexts, clarify that `identity` and `organizations` replaced `customers`. Not a one-line patch.

### Test changes

Per the user's brief: unit + integration + e2e, with testcontainers and mocked Supabase auth, covering success AND failure paths.

**Unit tests (domain + use cases, no I/O):**
- `tests/unit/identity/test_user_model.py` — `User` invariants
- `tests/unit/identity/test_register_user.py` — success + **idempotency**: duplicate `supabase_user_id` returns the existing User (no exception). Also asserts `RegisterUser.execute` is bindable to `RegisterUserPort` via callable Protocol (structural conformance).
- `tests/unit/identity/test_update_user_profile.py`
- `tests/unit/identity/test_find_user.py` — `by_id` returns User for known id + None for unknown (bindable to `UserLookupById`); `by_supabase_id` returns User for known sub + None for unknown.
- `tests/unit/shared_api/test_identity_middleware.py` — covers:
  - public path → bypass
  - `REGISTRATION_PATHS` → bypass User/membership checks, supabase_user_id attached
  - `/admin/*` + no User → 401
  - `/admin/*` + User + no memberships → 403
  - `/admin/*` + User + memberships → pass, state populated
  - `/portal/*` + User + no memberships → pass
  - `/portal/*` + User + memberships → pass (admins can hit portal)
- `tests/unit/shared_api/test_require_org_member.py` — dependency reads `request.state.memberships` directly; zero calls to any mocked `membership_repo` (verified via mock call count) (Q4 = 4a: unit test, not integration)
- `tests/unit/organizations/test_register_admin_account.py` — covers:
  - **Success (fresh sub):** `register_user` port called once → memberships lookup returns empty → Organization + OwnerMembership + Subscription created → composite returned.
  - **Duplicate account (sub with existing membership):** `register_user` port called (returns existing User per idempotency) → memberships lookup returns non-empty → raises a domain exception mapped to HTTP 409; **no** Organization created (assert via repo mock call count = 0).
  - **Step-3 retry (fresh sub, prior step-3 failure simulated):** `register_user` port returns existing User (no-op) → memberships empty (orphan from prior failure) → Organization created successfully → composite returned.

**Integration tests (real DB via testcontainers-postgres, real migrations, no external services):**
- `tests/integration/identity/test_user_repo.py` — CRUD on both `SupabaseUserRepository` and `SqlAlchemyUserRepository` (parametrised — the dual-adapter story requires both be tested)
- `tests/integration/identity/test_register_user_flow.py` — portal register endpoint end-to-end (without middleware bypassing; asserts User row created)
- `tests/integration/organizations/test_register_admin_account_flow.py` — admin register endpoint creates user + org + membership + subscription
- `tests/integration/organizations/test_membership_repo_with_org_names.py` — `list_by_user_id_with_org_names` returns the JOIN projection in a single query (asserted via query log); N+1 avoided

**e2e tests (FastAPI TestClient, testcontainers-postgres, mocked Supabase auth via HS256 tokens signed with the test JWT secret):**

For each scenario below, one **success** test and one **failure** test.

- `tests/e2e/identity/test_register_admin_flow.py`
  - Success: new Supabase sub → `POST /api/v1/admin/auth/register` → all four records exist after the call (User in identity, Organization + OwnerMembership + Subscription in organizations — created across two transactions per Q3 = 3.a, atomic from the caller's perspective) → `GET /api/v1/admin/auth/me` returns user with the membership (and `organization_name` populated from the JOIN) → admin endpoints work
  - Failure (duplicate admin): duplicate `supabase_user_id` **with existing memberships** → **409** "admin account already exists" (the duplicate-account check in step 2 of `RegisterAdminAccount`; no second Organization created).
  - Retry after step-3 failure: mock the Organization repo to raise on first call; first `POST /admin/auth/register` returns 5xx, User row orphaned. Retry the same request — step 1 no-ops (returns the orphan), step 2 passes (orphan has no memberships), step 3 succeeds — 201 Created with the composite response.
- `tests/e2e/identity/test_register_portal_flow.py`
  - Success: new Supabase sub → `POST /api/v1/portal/auth/register` → User created with no memberships → `GET /api/v1/portal/auth/me` returns `memberships: []` → portal endpoints work
  - Failure: no JWT → 401
- `tests/e2e/auth/test_admin_rejects_portal_token.py`
  - Success (rejection IS the success): portal user JWT → `GET /api/v1/admin/properties?organization_id=X` → 403 "no admin access"
  - Parametrised over every admin route discovered via `app.routes` (method-aware: GET uses query params, POST/PATCH uses minimal valid body; the 403 should fire at middleware layer before Pydantic validation)
- `tests/e2e/auth/test_portal_accepts_any_valid_token.py`
  - Success: admin JWT hits `/api/v1/portal/bookings` → works
  - Success: portal JWT hits `/api/v1/portal/bookings` → works
  - Failure: invalid JWT → 401
- `tests/e2e/auth/test_cross_tenant_check.py`
  - Setup: two orgs (A, B), two admins (one per org), one property per org
  - Success: admin-A `GET /api/v1/admin/properties?organization_id=<org-A-id>` → sees one property
  - Failure: admin-A `GET /api/v1/admin/properties?organization_id=<org-B-id>` → 403 from `require_org_member` (RLS is out of scope for this spec; app-layer check is the only line of defence)
- `tests/e2e/auth/test_membership_revocation_loses_admin.py`
  - Success: admin has membership → `/admin/*` endpoint → 200
  - Remove the membership via `DELETE /admin/memberships/{id}` (as a second admin who is OWNER)
  - Failure: same user, next request → 403 "no admin access" (proves admin-ness is derived at middleware time, not cached)
- `tests/e2e/identity/test_registration_bypass.py`
  - Success: `POST /api/v1/admin/auth/register` with valid JWT + user NOT in DB → succeeds (bypass works)
  - Success: `POST /api/v1/portal/auth/register` with valid JWT + user NOT in DB → succeeds
  - Failure: `POST /api/v1/admin/auth/register` with invalid JWT → 401

**Deleted tests (Q3 = 3b):** The 7 pre-existing `portal_user_repo`-constructor-error tests in `tests/e2e/` and `tests/integration/` get deleted along with the conftest rewrite. Any flow-level coverage they provided is picked up by the new e2e tests above.

**Test infra changes:**
- `tests/e2e/conftest.py` — rewrite the `Container(...)` constructor call to build `identity_container` + `organizations_container` (no `portal_user_repo` arg). Keep the `testcontainers-postgres` / LocalStack session-scoped fixtures. `SUPABASE_JWT_SECRET` test fixture continues issuing HS256 tokens.
- `tests/conftest.py` — replace `container` fixture with `identity_container` + `organizations_container`. Delete `portal_user_repo` fixture (lines 26, 108, 120, 130). Update `property_container` wiring if it consumes User from a new import path.
- `tests/adapters/test_database_models.py:20` — remove `"portal_users"` from the expected tables list.

## Acceptance criteria

### DDD split
- [ ] `src/identity/` exists with one aggregate (`User`), its own container, its own API routes. No imports from `organizations`.
- [ ] `src/organizations/` exists (formerly `src/customers/`). Owns Organization, Membership, Invitation, Subscription, Notification. Depends on `identity` only via the `UserLookupById` + `RegisterUserPort` callable Protocols (middleware's `find_user.by_supabase_id` call from shared infrastructure is permitted per Q2 = 2.b and is not counted as a cross-context dependency).
- [ ] **One-way dependency enforced**: `grep -rn "from organizations" src/identity/` → **zero hits**. `grep -rn "from identity" src/organizations/` → only matches in three expected sites: `organizations/application/use_cases/register_admin_account.py` (imports `RegisterUserPort` Protocol + calls identity via the binding), `organizations/adapters/api/routes/admin_auth.py` (imports `UserResponse` Pydantic schema for the composite register response), and `organizations/container.py` (where the Protocols are injected at construction time).
- [ ] `src/customers/` is gone. `grep -rn "from customers" src/ tests/` → zero hits.
- [ ] `PortalUser` class and `portal_user.py` are deleted. `portal_users` table is dropped. `grep -rni "portal_user" src/` → zero hits.
- [ ] `User.organization_id` is gone. `grep -rn "user\.organization_id\|users\.organization_id" src/` → zero hits.
- [ ] `src/organizations/adapters/database/` contains 5 per-aggregate repo files + per-aggregate model files — no `repositories.py` or `models.py` monolith. Same per-aggregate layout in `src/organizations/adapters/persistence/`.
- [ ] `src/identity/adapters/` contains both `persistence/supabase_user_repo.py` AND `database/user_repo.py` (dual-adapter preserved, Q1 = A1.a).

### Dual auth
- [ ] A portal user's JWT hitting any `/api/v1/admin/*` endpoint returns **403** "This account does not have admin access". Parametrised e2e test covers every admin route discovered via `app.routes`.
- [ ] An admin user's JWT hitting `/api/v1/portal/*` endpoints works.
- [ ] A JWT for a user not in the `users` table returns **401** "Unknown user" on any non-`REGISTRATION_PATHS` endpoint.
- [ ] Both `REGISTRATION_PATHS` (`/api/v1/admin/auth/register`, `/api/v1/portal/auth/register`) accept a valid JWT from a user not yet in the DB; the handler creates the User row.
- [ ] Revoking an admin's last membership causes the next request to 403. No cache, no logout required.
- [ ] `GET /auth/me` returns `{user: {...}, memberships: [{organization_id, role, organization_name, created_at}]}` under both admin and portal prefixes. Tests assert the shape; admin-prefix call 403s for a user with zero memberships.
- [ ] `require_org_member` reads from `request.state.memberships` — zero calls to `membership_repo`. Unit test (`tests/unit/shared_api/test_require_org_member.py`) verifies via mock call count (Q4 = 4a).
- [ ] Middleware's membership fetch is **one query**: `list_by_user_id_with_org_names` JOINs memberships + organizations in a single SQL statement. Integration test asserts via query log; no N+1 (A5).

### Migrations
- [ ] `alembic/versions/` contains exactly two files after this spec: the squashed baseline and the identity-split migration.
- [ ] **Baseline verification**: `pg_dump --schema-only --no-owner --no-privileges` against a DB built from the new baseline produces a byte-equivalent diff against a `pg_dump` of the pre-spec prod-shape DB (#10).
- [ ] `alembic upgrade head` on a fresh Postgres container runs clean end-to-end.
- [ ] `alembic downgrade -1` on a post-migration DB reverses cleanly (dev-only path).

### Quality
- [ ] All tests pass after the conftest rewrite + deletions from Q3. `uv run pytest` → green (no `portal_user_repo` errors — they're deleted per 3b).
- [ ] `uv run ruff check .` → clean.
- [ ] `/api/v1/admin/*` URL contracts are unchanged except `/auth/me` which gains the `memberships` array (breaking shape change; coordinated with frontend in the same PR cycle; not-in-prod so no external consumers break).
- [ ] `docs/features/identity.md` and `docs/features/organizations.md` replace `customers.md`. `README.md` bounded-contexts table updated. `CLAUDE.md` "Two Bounded Contexts" section rewritten to reflect 7 contexts.

## Open questions

All previously-open questions are now resolved:

- **Q1 — `RegisterAdminAccount` transactional boundary** = 1.a. Two transactions; `identity.register_user` idempotent on `supabase_user_id`; orphaned User on step-2 failure is acceptable (retry is safe). See Registration flow in Approach.
- **Q1 — Protocol ↔ use-case method naming** = 1.c. Callable Protocols bound to use-case methods at DI time (no adapter class, no method renames).
- **Q2 — Lookup-by-supabase-id** = 2.b. Middleware calls `identity_container.find_user.by_supabase_id(sub)` directly (shared infrastructure is not a bounded context). Only the cross-context `UserLookupById` lookup goes through a Protocol.
- **Q2 — `PortalUserResponse` schema callsites in frontend** = tracked as FE follow-up. Not-in-prod; FE migration happens in the same release window. No blocker for this spec.
- **Q3 — Rename in one or two commits** = two commits. Commit 1 = baseline squash; Commit 2 = mechanical `git mv` + import substitution; Commits 3–N = content changes. See commit ordering at the top of Approach.

No remaining open questions. Ready to implement.

## Out of scope follow-ups

- **`admin-rls-phase-one`** — Track 3 from the earlier draft. Stub at `.claude/specs/active/admin-rls-phase-one.md`. Starts with three spikes: supabase-py JWT mechanics, SQLAlchemy `auth.uid()` via `SET LOCAL`, testcontainers strategy.
- **Adapter consolidation** — collapse the dual `Supabase*Repository` + `SqlAlchemy*Repository` pattern onto a single adapter per port. Touches every context, not just identity/organizations. Own spec.
- Active-org JWT claim / switch-org endpoint (UX optimisation — remove explicit `organization_id` from admin request bodies)
- Role-based admin capabilities (use `MembershipRole` for authz decisions, not just "has membership")
- Promotion of `identity/` to a standalone service (at >1k DAU or if SSO federation arrives)
- SSO / multi-email-per-user / social provider linking
- Supabase Pro auth-hook migration (bake admin-ness + active-org into the JWT at issue time, removing the middleware DB lookups)
