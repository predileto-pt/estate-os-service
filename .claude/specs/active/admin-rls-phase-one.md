# Admin RLS rollout — Phase 1

**Status:** draft (blocked on spikes)
**Owner:** Peter
**Created:** 2026-04-18
**Depends on:** `identity-context-split-and-membership-auth` (must ship first)

## Problem

`src/shared/entrypoints/bootstrap.py:90,111` wires every Supabase client with `service_role_key`, which bypasses Row-Level Security entirely. The only thing scoping admin queries to an organization is the app-layer `require_org_member` dependency plus `WHERE organization_id = :org` filters in repository code. A single bug in either — a missing filter, a typo in a dependency — leaks cross-tenant data. There is no defence-in-depth at the database layer.

This became more pressing once `identity-context-split-and-membership-auth` made the admin-vs-portal boundary explicit: we now know exactly which tables need RLS (admin-scoped, org-keyed) and which callers should bypass (workers running as system, acting across tenants).

## Goal

Enable Supabase RLS on admin-scoped tables owned by `organizations` + `properties` bounded contexts so the database itself rejects cross-tenant reads and writes, with admin HTTP requests running as a per-request Supabase client that carries the caller's JWT (so `auth.uid()` resolves inside policies). Workers continue using `service_role_key`.

## Non-goals

- Portal-side RLS (Phase 2 — bookings, portal-accessible listings, portal's view of properties).
- Worker-side RLS — workers act on behalf of the system and continue using `service_role_key`. RLS policies are written to explicitly permit `service_role`.
- Role-based RLS (OWNER vs ADMIN vs MEMBER having different policies). Phase 1 uses "has any membership in this org" as the sole predicate.
- RLS on tables that don't have a straightforward `organization_id` FK (e.g., `users` — handled separately via `auth.uid() = supabase_user_id`; audit which tables this affects during Track 1).

## Approach

**Blocked on three technical spikes.** None of the downstream implementation is safe to commit to until these resolve. This spec starts with Track 0 (spikes); concrete tracks 1+ are written after spikes land answers.

### Track 0 — Spikes (required before acceptance criteria are meaningful)

Each spike lands a small proof-of-concept + a decision recorded back in this spec.

**Spike 1: supabase-py async client with per-request user JWT.**
Does `acreate_client(url, access_token=<jwt>)` actually carry the JWT through the PostgREST layer such that `auth.uid()` resolves server-side? Does the async client re-use the underlying httpx connection correctly, or does each call create a new one? If supabase-py doesn't cleanly support per-request JWTs, what's the workaround — direct `httpx` against PostgREST, a fork, a monkey-patch?
- **Deliverable:** one-file proof-of-concept in `scripts/spikes/` that passes a user JWT, calls a PostgREST endpoint against a real Supabase (staging) or `supabase/postgres` testcontainer, and asserts `SELECT auth.uid()` returns the expected sub.
- **Decision to record in this spec:** library path we're taking.

**Spike 2: SQLAlchemy `auth.uid()` via `SET LOCAL request.jwt.claim.sub`.**
The `properties`, `screening`, `bookings`, `contract_intelligence`, and `listings` contexts use SQLAlchemy with `asyncpg`, NOT PostgREST. For RLS policies referencing `auth.uid()` to work on those tables, each transaction needs `SET LOCAL request.jwt.claim.sub = '<user-id>'`. Open questions:
- Does this work with async SQLAlchemy + asyncpg?
- Can it be wired via a session factory event hook (on `after_begin`) so it runs automatically per transaction, rather than requiring every query to set it manually?
- How do we get the user's sub into the session factory from the middleware without leaking request state into repository code?
- **Deliverable:** one integration test that (a) seeds a `properties` row via service_role, (b) opens a SQLAlchemy session configured with user-B's sub, (c) asserts user-B can't SELECT the row created by user-A, (d) service_role session sees everything.
- **Decision to record in this spec:** the wiring mechanism (session event hook vs. explicit per-query vs. connection pool scoping).

**Spike 3: Testcontainers strategy.**
A plain `postgres:16` image does not have `auth.uid()`, `auth.users`, or Supabase's policy helper functions. Options:
- **3a.** Use `supabase/postgres` image in testcontainers. Heavier (~500MB vs 200MB for plain postgres), closer to prod, includes pg_jwt extension.
- **3b.** Write a test shim — a test-only migration that creates `auth.uid() RETURNS uuid AS $$ SELECT current_setting('request.jwt.claim.sub', true)::uuid $$ LANGUAGE sql STABLE;`. Tests stay fast; risk is tests pass but prod behavior differs (e.g., Supabase's actual `auth.uid()` returns NULL when no claim is set; shim returns NULL by the `true` flag — behaviorally equivalent, but any future Supabase-specific extension use would drift).
- **Deliverable:** a fixture in `tests/infrastructure/conftest.py` that spins up whichever strategy we pick; the Spike 1+2 tests run in CI green.
- **Decision to record in this spec:** image vs. shim, with the tradeoff note.

### Tracks 1+ (to be written after Track 0 resolves)

Placeholder — will be filled in once spikes answer:

- **Track 1: RLS policy authoring and migration.** Enable RLS on:
  - `organizations`, `memberships`, `invitations`, `subscriptions`, `notifications`
  - `properties`, `property_owners`, `property_amenities`, `property_images`, `property_prices`
  - `extraction_jobs`, `document_content`
  - Also decide: `users` (via `auth.uid() = supabase_user_id`) — preferred yes, for defence-in-depth on the identity table itself.
- **Track 2: Request-scoped admin container / session factory.** Factory that constructs the right Supabase / SQLAlchemy session with user-JWT context injected (mechanism from Spike 2).
- **Track 3: Admin route migration.** Every admin FastAPI route migrates from `request.app.state.*_container` to a `Depends(admin_container).*` pattern that resolves the request-scoped factory. Worker entrypoints unchanged.

### Atomicity concern

Once RLS is enabled on a table, any code path reading that table via a session that doesn't have `auth.uid()` set (or isn't service_role) returns empty/denies. That means Track 1 (enable RLS) and Track 2/3 (wire request-scoped clients) must ship in the same release, OR we ship in two phases with a feature flag gating the policies. Decision pending Spike 2 — if the session-factory wiring turns out to be low-risk, a single release is fine; if it touches every repository, a feature-flag rollout may be safer.

## Affected files / surfaces

**TBD — depends on Track 0 outcomes.** Skeleton:

- New: `alembic/versions/<stamp>_rls_phase_one.py` — enable RLS + create policies
- Updated: `src/shared/entrypoints/bootstrap.py` — request-scoped factories
- Updated: every admin route under `src/*/adapters/api/routes/` — DI pattern change
- Updated: `tests/infrastructure/conftest.py` — Supabase-flavoured test DB fixture
- New: `tests/integration/rls/test_*_policies.py` — per-table parametrised RLS tests

## Acceptance criteria

**Cannot be written meaningfully without Spike outcomes.** Skeleton criteria:

- [ ] `SELECT * FROM pg_tables WHERE rowsecurity = true` includes every Phase 1 table listed in Track 1.
- [ ] Parametrised integration test `tests/integration/rls/test_policies.py` — for each Phase 1 table, a user-JWT session sees only their org's rows, cross-org read returns empty, cross-org write is denied, service_role sees everything.
- [ ] Admin FastAPI routes resolve their DB access via a per-request factory carrying the caller's JWT. Verified by a test that spins up two concurrent requests with different JWTs and asserts data isolation.
- [ ] Workers (SQS/SNS consumers, scheduled jobs) continue using `service_role_key`. No worker entrypoint gains a user-JWT path.
- [ ] All three Spike 0 decisions documented inline in this spec (library path, session wiring mechanism, testcontainer strategy).

## Open questions

- **All three spikes above.**
- **RLS on `users` itself?** — preferred yes, via `auth.uid()::text = supabase_user_id`, so the identity table gets the same defence-in-depth as the business tables.
- **Feature-flag rollout vs. atomic release** — see "Atomicity concern" above.
- **Policy shape for write paths.** `WITH CHECK` clauses need careful thought: an admin creating a property for their own org should succeed; creating one for another org should fail. Naive policy might allow `UPDATE properties SET organization_id = <other-org>` if `WITH CHECK` isn't mirrored on the row's *old* and *new* state.
- **Testcontainers performance.** If we go with `supabase/postgres` image, CI time per test file goes up. Worth benchmarking during Spike 3.

## Out of scope follow-ups

- Portal-side RLS (Phase 2) — bookings, portal-accessible listings, portal's view of user data
- Worker-side RLS (Phase 3 — probably never: workers genuinely need service_role to act on behalf of the system)
- Role-based admin capabilities (use `MembershipRole` for policy differentiation, not just "has membership")
- Supabase Pro auth-hook migration (bake admin-ness + active-org into the JWT at issue time, removing per-request middleware DB lookups)
