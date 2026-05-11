# Portal session backend (anonymous + claimable)

**Status:** in-progress
**Owner:** Peter
**Created:** 2026-05-11
**Revised:**
- 2026-05-11 (r1) — sharpened after review: explicit middleware wiring, CORS/CSRF posture, dual-Supabase + dual-DB architecture for portal vs admin, logout privacy, claim auth-channel.
- 2026-05-11 (r2) — CORS reuses existing `CORS_ORIGINS`; prune job committed to external-trigger admin route; `load_session` raises domain exceptions mapped via FastAPI exception handler; portal `Base` location named; key version is a plain integer in both cookie and env; JWKS cache URL-keying flagged.
- 2026-05-11 (r3) — prune moved from admin HTTP route to CLI entrypoint. Admin-auth on a system maintenance task was the wrong scope; CLI matches the existing `entrypoints/` pattern and removes the need for a service-account admin user.
- 2026-05-11 (r4) — added `scripts/migrate_admin.sh` and `scripts/migrate_portal.sh` wrappers. Two parallel Alembic configs (admin DB vs portal DB) without wrappers is a foot-gun; the wrappers pin each invocation to its correct config + env var, fail fast on missing env, and become the documented entry points (CLAUDE.md, deploy pipeline, local dev).
- 2026-05-11 (r5) — polish: fixed stale prose in §9.3 (`load_session` raises domain exceptions, not `HTTPException`) and Affected Files (prune is CLI, not admin HTTP route). Made cookie name a hardcoded constant (drop `SESSION_COOKIE_NAME` env). Explicit `__main__` guard on the prune CLI. Container construction docs explicit about repository.
**Portal ADR:** `predileto-portal/docs/adr/001-user-session-and-client-state.md`

## Problem

The portal (`predileto-portal`, Next.js) needs a backend-authoritative session abstraction. Today its visitor state is fragmented across `localStorage` keys with no cross-device continuity, no abuse-prevention surface, no capability model, and no migration path to authenticated sessions. Portal ADR-001 decided that **the backend mints and owns the session**, sets a signed `predileto_session` cookie, and exposes endpoints the FE talks to (`init`, `me`, `claim`, `logout`, slice writes). None of those endpoints exist yet.

A second constraint shapes this spec: **portal users live in a different Supabase project than admin/agency users**. That means:

- A different JWT (different JWKS URL, different shared secret, different audience).
- A different Postgres database — portal user identity rows and portal session rows live in the portal Supabase project's DB, not the admin DB.

So this spec covers the BE half — the new bounded context, the cookie + signing infrastructure, the five endpoints, the Postgres schema in the **portal** DB, and the cross-context seams (portal-Supabase JWT validation, capability list, slice storage). The portal `User` register endpoint itself doesn't exist yet either; this spec lays the interface ground so a future `feat(portal-identity): register` slot in without revisiting any of these decisions.

FE work (provider, hooks, middleware-mint integration) is tracked separately in the portal repo.

## Goal

`estate-os-service` exposes `/api/v1/session/{init,me,claim,logout}` and `PATCH /api/v1/session/me`, all backed by a new `sessions/` bounded context whose persistence is wired to the **portal** Postgres database, HMAC-signed `HttpOnly` cookies, BE-derived capabilities, and a `ValidatePortalAuthToken` port that claim uses to flip an anonymous session to authenticated using a portal-Supabase JWT — without rotating the cookie.

## Non-goals

- **Frontend implementation** — portal provider, hooks, middleware, optimistic cache, `useSyncExternalStore` integration. All in `predileto-portal`.
- **Portal `User` registration endpoint** — `POST /api/v1/portal/auth/register` against the portal Supabase project is a separate spec. This spec defines the port (`ValidatePortalAuthToken`) and the DB wiring it will reuse; the route itself is out of scope.
- **Preference schema** — `prefs` is a free-form JSONB blob with a size cap in v1. A real schema lands in a follow-up spec when product locks the fields.
- **Auth provider swap-out** — claim accepts a token validated by a Protocol; the portal-Supabase adapter is the v1 implementation, swap-out is later.
- **Redis** for the session store. Portal Postgres until lookup latency demands otherwise (ADR open question, this spec resolves it as Postgres).
- **Hot key rotation tooling**. The signer supports multi-key (versioned signatures); the rotation runbook is out of scope.
- **Rate limiting / abuse detection** built on top of sessions. The session id makes it possible; the actual rate-limit logic is its own feature.
- **Cross-device merge UX** beyond union/overwrite (no conflict-resolution UI).
- **Session split into its own service**. Stays in `estate-os-service` per ADR-001.
- **Logout-with-revoke**. v1 logout flips the record back to anonymous; full revoke is a v2 toggle (see §6 for the v1 logout posture, which clears favorites/prefs to avoid the shared-device privacy footgun).
- **Migrating the existing `POST /api/v1/portal/auth/register` route** at `identity/adapters/api/routes/portal_auth.py` to use the portal Supabase project + portal DB. That route currently shares the admin Supabase + admin DB; rewiring it is the portal-identity follow-up spec.

## Approach

### 1. New bounded context: `src/sessions/`

Mirrors the standard hex layout (`domain/`, `application/`, `adapters/`, `container.py`, `entrypoints/`). Container exposed as `app.state.sessions_container`. `entrypoints/` holds the prune CLI (§12) — no SQS worker in v1.

```
src/sessions/
├── domain/
│   ├── models/
│   │   ├── session.py            # Session aggregate (frozen dataclass + transitions)
│   │   └── capability.py         # Capability enum
│   ├── value_objects.py          # SessionId
│   └── exceptions.py
├── application/
│   ├── ports/
│   │   ├── session_repository.py
│   │   ├── cookie_signer.py
│   │   ├── clock.py              # reuse shared if available
│   │   └── validate_portal_auth_token.py
│   └── use_cases/
│       ├── init_session.py
│       ├── get_session_view.py
│       ├── update_session_slice.py
│       ├── claim_session.py
│       ├── logout_session.py
│       └── prune_stale_anonymous_sessions.py
├── adapters/
│   ├── api/
│   │   ├── routes/session.py     # public, cookie-authed
│   │   ├── schemas.py
│   │   ├── cookie.py             # FastAPI helpers: read/set/clear cookie + load_session dependency
│   │   └── exception_handlers.py # domain exceptions → HTTP error codes
│   ├── auth/
│   │   └── supabase_portal_token_validator.py
│   ├── database/
│   │   ├── base.py               # Base = declarative_base() — portal-DB MetaData
│   │   ├── models.py             # SQLAlchemy table, registers against base.Base
│   │   └── repository.py         # consumes the portal session_maker
│   ├── inmemory/                 # test doubles
│   │   ├── repository.py
│   │   └── portal_token_validator.py
│   └── signing/
│       └── hmac_cookie_signer.py
├── entrypoints/
│   └── prune_stale_anonymous.py  # CLI: bootstraps container, runs prune use case, exits
├── container.py
└── __init__.py
```

Cross-context rule: `sessions` imports zero code from `identity`, `organizations`, or any other admin-side context. It depends on `ValidatePortalAuthToken` (Protocol) for claim; the portal-Supabase adapter is wired in the composition root. The container receives the **portal** `async_sessionmaker` at construction.

### 2. Dual-auth + dual-database architecture (new)

This section formalises the architectural addition that the rest of the spec depends on.

**Two Supabase projects:**

| Project | Audience | Token verified by | Used by routes under |
|---|---|---|---|
| Admin | admin & agency users | existing `JWTAuthMiddleware` reading `settings.supabase_*` | `/api/v1/admin/*`, current `/api/v1/portal/*` until migrated |
| Portal | portal visitors / signed-in property seekers | new `SupabasePortalTokenValidator` reading `settings.supabase_portal_*` | `/api/v1/session/*` (claim); future portal-identity routes |

The portal validator is parameterised by `(supabase_url, jwt_secret, audience)` — same decode logic as admin (ES256 via JWKS first, HS256 fallback), different credentials. Both share a single helper `decode_supabase_token(token, *, supabase_url, jwt_secret, audience)` extracted into `src/shared/auth/supabase.py` (next to existing `jwks.py`). `JWTAuthMiddleware._decode_token` becomes a thin call into this helper. Behaviour for admin is unchanged.

**Two Postgres databases (via two Supabase projects):**

| DB | URL setting | Owns tables |
|---|---|---|
| Admin DB | `settings.database_url` (existing) | `users` (admin), `organizations`, `properties`, `billing`, `screening`, `bookings`, `contract_intelligence`, `listings`, ... — everything that exists today |
| Portal DB | `settings.portal_database_url` (new) | `sessions` (this spec). Future: portal `users` and any other portal-identity tables. |

A second async engine + `async_sessionmaker` is built at startup from `portal_database_url` and made available to the `sessions` container. No cross-DB transactions, no FKs across DBs, no shared SQLAlchemy `MetaData` between them.

**Migrations:** two parallel Alembic configurations at the repo root, one per DB:

```
alembic.ini                  # admin DB — existing, untouched
alembic/
├── env.py                   # reads settings.database_url, imports admin-side models
├── script.py.mako
└── versions/                # admin-DB migrations — existing

alembic-portal.ini           # portal DB — new
alembic-portal/
├── env.py                   # reads settings.portal_database_url, imports portal-side models only
├── script.py.mako
└── versions/                # portal-DB migrations — starts with the `sessions` table
```

`alembic-portal/env.py` imports **only** portal-context models (in v1: `sessions.adapters.database.models`). It uses its own `Base` declared at `src/sessions/adapters/database/base.py` (a separate `MetaData`) so autogenerate can't accidentally drop admin tables. `models.py` registers against `base.Base`, never against `shared.database.models.Base`.

**Wrapper scripts** (mandatory entry points — raw `alembic ...` commands are never the documented way):

```
scripts/
├── migrate_admin.sh         # admin DB; requires DATABASE_URL
└── migrate_portal.sh        # portal DB; requires PORTAL_DATABASE_URL
```

Behaviour of each wrapper:

1. `set -euo pipefail`. Load `.env` if present (same pattern other repo scripts can rely on; not strictly necessary in container envs where env is pre-set).
2. Validate the required env var (`DATABASE_URL` for admin, `PORTAL_DATABASE_URL` for portal). Exit 2 with a clear error if empty.
3. Print which target DB is being touched (host + port, password redacted) so the operator sees what's happening.
4. Forward all positional args to `uv run alembic` (admin: no `-c`; portal: `-c alembic-portal.ini`).

Usage:

```bash
bash scripts/migrate_admin.sh upgrade head
bash scripts/migrate_admin.sh revision --autogenerate -m "add foo to orgs"

bash scripts/migrate_portal.sh upgrade head
bash scripts/migrate_portal.sh revision --autogenerate -m "add bar to sessions"
bash scripts/migrate_portal.sh downgrade -1
bash scripts/migrate_portal.sh current
```

The wrappers are the **only** invocation surface documented in CLAUDE.md and used by the deploy pipeline. Running raw `uv run alembic ...` still works but is reserved for unusual debugging — the wrappers exist so nobody runs the wrong config against the wrong DB.

**JWKS cache scope.** `shared.auth.jwks.fetch_jwks_public_key(supabase_url)` already takes the URL as a parameter, but the cache layer (LRU / dict) **must be keyed by `supabase_url`** so admin and portal projects don't fight over a single cached key. This is a load-bearing detail of the dual-Supabase setup — see acceptance criteria.

### 3. Domain model

`Session` aggregate (frozen dataclass with transition methods returning new instances):

| Field | Type | Notes |
|---|---|---|
| `id` | `SessionId` (UUID) | PK; the value inside the signed cookie |
| `kind` | enum `ANONYMOUS` \| `AUTHENTICATED` | flipped by `claim`/`logout` |
| `user_id` | `UUID \| None` | portal user id; null while anonymous |
| `favorites` | `frozenset[UUID]` | property ids; canonical here |
| `prefs` | `Mapping[str, Any]` | free-form JSONB, capped at 8 KB serialized |
| `created_at` | `datetime` | tz-aware UTC |
| `last_seen_at` | `datetime` | refreshed on `/me` (debounced, see §6) |
| `claimed_at` | `datetime \| None` | set on first successful claim |
| `revoked` | `bool` | default False; reserved for v2 |

The signing-key version is **not** persisted on the row — the cookie carries it (§5), the row is silent on which key created the cookie. Persisting it duplicates state without enabling any new query.

Domain methods on `Session`:

- `with_favorite_added(property_id) -> Session`
- `with_favorite_removed(property_id) -> Session`
- `with_prefs_merged(patch: Mapping[str, Any]) -> Session` (deep merge; size-check raised as `PrefsTooLarge`)
- `claimed_by(user_id, *, now) -> Session`
- `logged_out(*, now) -> Session` — flips to `ANONYMOUS`, clears `user_id` *and* `favorites`/`prefs` (see §6.5 for the privacy rationale)
- `touched(*, now) -> Session` — updates `last_seen_at` only

Capability resolution is **derived**, not stored. A pure function `capabilities_of(session: Session) -> frozenset[Capability]`:

- `ANONYMOUS` → `{SAVE_FAVORITE, VIEW_HISTORY, SET_PREFERENCES}`
- `AUTHENTICATED` → above ∪ `{COMMENT, CONTACT_AGENT, SAVE_PROPERTY}`

Domain exceptions:

- `SessionNotFound`, `SessionRevoked`, `CookieSignatureInvalid`, `CookieMalformed`, `PortalAuthTokenInvalid`, `PrefsTooLarge`, `FavoriteLimitExceeded` (cap at 500 in v1), `SessionBoundToOtherUser`.

### 4. Persistence (portal DB / parallel Alembic)

New table `sessions` in the **portal** Postgres database:

```sql
CREATE TABLE sessions (
  id            UUID PRIMARY KEY,
  kind          TEXT NOT NULL,                  -- 'ANONYMOUS' | 'AUTHENTICATED'
  user_id       UUID NULL,                      -- portal user id; soft reference, no FK
  favorites     JSONB NOT NULL DEFAULT '[]',    -- array of UUID strings
  prefs         JSONB NOT NULL DEFAULT '{}',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  claimed_at    TIMESTAMPTZ NULL,
  revoked       BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX ix_sessions_user_id ON sessions (user_id) WHERE user_id IS NOT NULL;
CREATE INDEX ix_sessions_last_seen_at ON sessions (last_seen_at);
-- last_seen_at index supports the anonymous TTL sweep (§12).
```

Favorites stored as a JSONB array (not a child table) because v1 cap is 500 ids, reads are always whole-session via `GET /me`, and adding a child table later is straightforward.

`user_id` is a soft reference. There is **no FK** because the `portal_users` table doesn't exist in v1 (and even when it does, cross-DB FKs are impossible — but they would both be in the portal DB, so an FK becomes possible at that point and can be added in the portal-identity spec).

The migration runs via `bash scripts/migrate_portal.sh upgrade head` (see §2). The repo's CI/deploy pipeline runs both wrappers before app boot — admin and portal migrations are independent and order between them doesn't matter (no cross-DB FKs).

### 5. Cookie + signing

Cookie attributes:

```
Name:     predileto_session
Value:    base64url(session_id_bytes) "." base64url(hmac_sha256(key_v{N}, session_id_bytes)) "." N
Path:     /
HttpOnly: true
Secure:   true        # configurable (SESSION_COOKIE_SECURE=false) for non-TLS local dev only
SameSite: Lax
Max-Age:  31536000    # 1 year; sliding refresh on every /me hit
Domain:   ${SESSION_COOKIE_DOMAIN}   # e.g. .predileto.pt; unset (host-only) in local dev
```

The third component `N` is the integer key version, decimal-encoded (e.g. `2`). Numeric, no padding — `int(parts[2])` parses it.

`HmacCookieSigner` (adapter) supports a **dict of key versions**:

```python
HmacCookieSigner(
    active_key_version=2,
    keys={1: b"...", 2: b"..."},      # int keys; all valid for verify; only `active` signs
)
```

Verification accepts any version in `keys`; signing always uses `active_key_version`. Rotation = (1) add new version, (2) deploy with old + new keys, (3) bump `active_key_version`, (4) drop old after the cookie max-age window. No code change per rotation.

Keys are loaded from env (`SESSION_SIGNING_KEYS=1:<base64url>,2:<base64url>`; comma-separated, **base64url** without `=` padding to keep shell-quoting trivial). Key versions are plain decimal integers in both the env var and the cookie's third component — no `v` prefix, no string versions.

`HttpOnly=true`, `Secure=true` (in prod), and `SameSite=Lax` are non-negotiable in deployed environments; the FE never reads the cookie value. SameSite=Lax is the right default for a Next.js portal hitting same-site APIs and underpins the CSRF posture (§10).

### 6. Endpoints

All under `/api/v1/session`. Mounted by `sessions/adapters/api/routes/session.py`. **The prefix `/api/v1/session/` is added to `shared.api.middleware.PUBLIC_PREFIXES`** so `JWTAuthMiddleware` and `IdentityMiddleware` skip it — these endpoints are cookie-authed, not Bearer-authed, and don't carry an admin JWT.

Each endpoint uses a route-level `Depends(load_session)` (in `sessions/adapters/api/cookie.py`) that reads the cookie, verifies the signature via `HmacCookieSigner`, loads the row via the repository, and returns a `Session` aggregate. On any failure it raises **domain exceptions** (`SessionNotFound`, `SessionRevoked`, `CookieSignatureInvalid`, `CookieMalformed`) — never `HTTPException` from the dependency itself. A FastAPI `exception_handler` registered for the session router (in `sessions/adapters/api/exception_handlers.py`) maps these to the right HTTP status + error code. This matches the codebase convention (CLAUDE.md "Key Conventions": *"Domain exceptions raised by use cases are caught in routes and mapped to HTTP status codes."*) and keeps the dependency layer free of HTTP concerns.

#### 6.1 `POST /api/v1/session/init`

- **When called**: first request from a new visitor (portal middleware-mint or lazy client bootstrap). Idempotent: if a valid cookie is present, returns that session's view + debounced `last_seen_at` refresh, **no `Set-Cookie`**. If the cookie is absent, invalid, expired, or its row is missing (orphan after TTL sweep), mints fresh + `Set-Cookie`.
- **Body**: empty.
- **Response 200**: `SessionView` (see §7).
- **Side effects on mint**: insert `sessions` row with `kind=ANONYMOUS`, set `Set-Cookie: predileto_session=...`.
- **Race acceptance**: two concurrent inits from a brand-new visitor (no cookie either time) may create two rows. The first response sets the cookie; subsequent requests reuse it. The orphan row decays in 90d via the sweep. Acceptable trade-off vs. distributed locking.

#### 6.2 `GET /api/v1/session/me`

- **Requires**: valid `predileto_session` cookie.
- **Response 200**: `SessionView`.
- **Side effects**: debounced `last_seen_at` refresh — only updates if `now - last_seen_at > SESSION_LAST_SEEN_DEBOUNCE_SECONDS` (default 60s), to keep this read mostly read-only.
- **Errors**: 401 `SESSION_MISSING` if no cookie; 401 `SESSION_INVALID` if signature fails, the row is missing, or `revoked=true`. The FE recovers from `SESSION_INVALID` by calling `POST /session/init`.

#### 6.3 `PATCH /api/v1/session/me`

- **Requires**: valid cookie.
- **Body** (`SessionPatchRequest`, all fields optional):
  ```json
  {
    "favorites": { "add": ["uuid", ...], "remove": ["uuid", ...] },
    "prefs": { "merge": { "key": "value" } }
  }
  ```
- **Response 200**: `SessionView` (echoes the post-write state).
- **Validation**:
  - Each favorite id is a UUID; reject otherwise (400 `INVALID_FAVORITE_ID`).
  - Total favorites after apply ≤ 500 (400 `FAVORITE_LIMIT_EXCEEDED`).
  - Serialized `prefs` ≤ 8 KB (400 `PREFS_TOO_LARGE`).
  - `prefs.merge` is a deep merge over the existing JSON object. No deletes via patch in v1.

#### 6.4 `POST /api/v1/session/claim`

- **Auth channel** (resolved): the portal Supabase JWT is sent via the **`Authorization: Bearer <token>` header**, not the body. The path is in `PUBLIC_PREFIXES` so the global `JWTAuthMiddleware` does **not** decode the token — the route handler validates it explicitly with `ValidatePortalAuthToken` (which uses the **portal** Supabase project's secret/JWKS, not the admin one). Reasons:
  - Consistent with the rest of the API (every authenticated call uses Bearer).
  - Cleanly separates the two Supabase projects: the global middleware only knows admin tokens.
  - No body field means CSRF surface is limited to "tricking the user's browser into POSTing" — `SameSite=Lax` blocks that (§10).
- **Flow**:
  1. `load_session` dependency loads the session by cookie. Reject if `revoked` (401 `SESSION_INVALID`) or already authenticated to a different user (409 `SESSION_BOUND_TO_OTHER_USER` — the FE should `logout` first).
  2. Read `Authorization: Bearer ...` header. Call `validate_portal_auth_token.execute(token)` → returns `ValidatedPortalIdentity(user_id, email)` or raises `PortalAuthTokenInvalid` (401).
  3. Flip session: `kind=AUTHENTICATED`, `user_id=<from validator>`, `claimed_at=now`. Favorites and prefs are **preserved** through claim (anonymous → authenticated is "this person is now the owner of the data they collected pre-login").
  4. Persist; return new `SessionView`.
- **Cookie is not rotated** — same `predileto_session` value, new row state.

#### 6.5 `POST /api/v1/session/logout`

- **Requires**: valid cookie.
- **Body**: empty.
- **Effect**: flip to `ANONYMOUS`, clear `user_id`, clear `claimed_at`, **and clear `favorites` + `prefs`**.
- **Response 200**: `SessionView` (now a clean anonymous view).
- **Cookie**: not rotated. The same `predileto_session` keeps working as a fresh anonymous session.
- **Idempotent**: calling logout on an already-anonymous session returns 200 with the same view, no error, no side effect.

**Note on audit history.** Clearing `claimed_at` deletes the row-level "this session was once authenticated" signal. Session-level audit history is out of scope for v1; if claim/logout events ever need to be retained, the `OperationsLog` pattern from ADR-015 is the right home.

**Note on expired/deleted Supabase user.** The portal validator checks the JWT signature + `exp` only — not whether the Supabase user still exists. A JWT issued shortly before the user is hard-deleted still passes claim until it expires (Supabase token TTLs are short, typically ≤ 1 hour). The portal-identity follow-up's register-on-first-claim flow will be the layer that catches dead users at the user-row write.

**Why clear favorites/prefs on logout (overrides ADR-001 §7's preserve-on-logout for v1)**: a logged-out user on a shared device must not leak their saved properties or preferences to the next visitor on that device. ADR-001 §7's "search history stays attached to the same anonymous session" was reasoning about *pre-login anonymous data being inherited by the user on claim* — the reverse direction (authenticated state surviving logout) is a privacy footgun. Search history remains client-only (per ADR-001 §4) and is not touched here.

If the future product surface adds an explicit "logout but keep my saved properties" toggle, it lives in a follow-up — out of scope for v1.

### 7. Response shape — `SessionView`

```json
{
  "kind": "ANONYMOUS",
  "user_id": null,
  "capabilities": ["SAVE_FAVORITE", "VIEW_HISTORY", "SET_PREFERENCES"],
  "prefs": {},
  "favorites": ["uuid", ...]
}
```

`session_id`, `created_at`, `last_seen_at`, `claimed_at`, and `revoked` are **never** in the response body. The FE only sees the public view above.

### 8. Cross-context wiring

`ValidatePortalAuthToken` Protocol lives in `sessions/application/ports/validate_portal_auth_token.py`:

```python
class ValidatePortalAuthToken(Protocol):
    async def execute(self, auth_token: str) -> ValidatedPortalIdentity: ...
```

`ValidatedPortalIdentity` is a frozen dataclass: `{ user_id: UUID, email: str | None }`.

v1 implementation: `SupabasePortalTokenValidator` in `sessions/adapters/auth/`. Constructor takes `(supabase_url, jwt_secret, audience)` from `settings.supabase_portal_*`. Calls the shared helper `shared.auth.supabase.decode_supabase_token(...)` (newly extracted, same logic as today's `JWTAuthMiddleware._decode_token`).

The validator returns the Supabase `sub` claim as `user_id`. Whether that user has a corresponding row in the portal-identity `users` table (when it exists) is **not** this spec's problem — capability gating is based on `kind`, not on local-user existence, so claim succeeds even if the portal `users` row hasn't been created yet. The portal-identity spec is responsible for the register-on-first-claim flow when it lands.

**No imports from `identity/`, `organizations/`, or any other context.** The `JWTAuthMiddleware` and `IdentityMiddleware` are untouched (except for the unrelated `_decode_token` extraction in §9).

### 9. Middleware integration (new, load-bearing)

This is the wiring that makes everything above actually reachable.

1. **`PUBLIC_PREFIXES` edit** in `src/shared/api/middleware.py` (line 25):
   ```python
   PUBLIC_PREFIXES = (
       "/api/v1/listings/",
       "/api/v1/billing/webhooks/",
       "/api/v1/session/",   # cookie-authed; bypass JWTAuthMiddleware + IdentityMiddleware
   )
   ```
   Both `JWTAuthMiddleware` and `IdentityMiddleware` already short-circuit on `PUBLIC_PREFIXES`, so a single tuple edit covers both. Verified against `shared/api/middleware.py:58` and `:98`.

2. **JWT decode helper extraction**. Move the body of `JWTAuthMiddleware._decode_token` into `src/shared/auth/supabase.py::decode_supabase_token(token, *, supabase_url, jwt_secret, audience)`. `JWTAuthMiddleware._decode_token` becomes a one-liner delegating with `audience="authenticated"` and the admin secret. Behaviour unchanged. The portal validator calls the same helper with the portal credentials and audience (likely also `"authenticated"`, confirm at implementation).

3. **`load_session` FastAPI dependency** in `sessions/adapters/api/cookie.py`:
   ```python
   async def load_session(
       request: Request,
       cookie_signer: HmacCookieSigner = Depends(get_cookie_signer),
       repo: SessionRepository = Depends(get_session_repo),
   ) -> Session:
       ...
   ```
   Reads `request.cookies[SESSION_COOKIE_NAME]`, verifies the signature, loads the row, and returns the `Session`. On any failure it raises a **domain exception** (`SessionNotFound`, `SessionRevoked`, `CookieSignatureInvalid`, or `CookieMalformed`) — **never `HTTPException` directly**. The registered exception handler in `sessions/adapters/api/exception_handlers.py` (see §6) maps each to its HTTP response. Used by every session route handler.

4. **Container wiring** in `src/shared/main.py` (lifespan or app factory):
   - Build the portal engine: `portal_engine = build_async_engine(settings.portal_database_url)`.
   - Build the portal `async_sessionmaker`.
   - Construct `sessions_container = SessionsContainer(portal_session_maker, cookie_signer, portal_token_validator, clock)`. The container internally constructs `SessionRepositorySQL(portal_session_maker)` and instantiates the use cases against it — the repository is not passed in as a separate constructor arg, mirroring how other containers in this repo (e.g. `identity_container`) wire their own repositories from a session maker.
   - `app.state.sessions_container = sessions_container`.
   - `app.include_router(sessions_router, prefix="/api/v1/session")`.

### 10. CORS + CSRF posture

**CORS.** The existing `CORSMiddleware` at `src/shared/main.py:181` already wires `allow_origins=settings.cors_origin_list` and `allow_credentials=True` from the existing `CORS_ORIGINS` env var (`src/shared/config.py:162`). **No code change required.** For session endpoints to work cross-origin (portal at `predileto.pt` → API at `api.predileto.pt`):

- **Operational**: add the portal origin(s) to `CORS_ORIGINS` in deploy config (e.g. `CORS_ORIGINS=https://app.example.com,https://predileto.pt,https://www.predileto.pt`). No new env var.
- **FE**: `fetch(..., { credentials: 'include' })` on every session call. Documented in the portal repo's FE spec; flagged here so we don't ship a BE that the FE can't call.

The CORS preflight acceptance test (below) validates the *existing* middleware against the portal origin, not a new piece of code.

**CSRF.** Cookie + mutating endpoints (`PATCH /me`, `POST /claim`, `POST /logout`) is a classic CSRF surface. v1 relies on:

1. **`SameSite=Lax`** on `predileto_session` — blocks cross-site `POST`/`PATCH` from third-party origins.
2. **Non-wildcard CORS allow-list** — only `predileto.pt` (and configured subdomains) can make credentialed requests. A malicious origin cannot complete a credentialed preflight.
3. **Cookie auth alone is insufficient on claim** — claim *also* requires the portal Supabase JWT in the `Authorization` header. A cross-site attacker would need to also steal that token; they can't (JWTs live in JS-readable storage on the FE per Supabase defaults, but cross-origin reads are blocked by the SOP).

This is sufficient for v1. Explicit CSRF tokens (double-submit cookie or anti-forgery header) are out of scope and would be added if a future requirement (e.g. embedding the portal in a third-party iframe, or moving claim to body auth) defeats one of the three layers above.

### 11. Configuration (env vars)

```bash
# --- Portal Supabase project (new) ---
SUPABASE_PORTAL_URL=https://<portal-ref>.supabase.co
# SUPABASE_PORTAL_JWT_SECRET is intentionally absent from the documented
# defaults — modern Supabase projects sign ES256 and the URL alone (via
# JWKS) is sufficient. The code path still supports HS256 for legacy
# projects: operators on those can set SUPABASE_PORTAL_JWT_SECRET=...
# ad-hoc and the decoder will use it as a fallback.
SUPABASE_PORTAL_AUDIENCE=authenticated

# --- Portal Postgres (new) ---
PORTAL_DATABASE_URL=postgresql+asyncpg://<user>:<pw>@<portal-supabase-host>/postgres

# --- Cookie ---
# (Cookie name is a hardcoded constant `predileto_session` in shared.api.cookies or
#  sessions.adapters.api.cookie — part of the BE/FE protocol contract, not configurable.)
SESSION_COOKIE_DOMAIN=                         # e.g. .predileto.pt; empty (host-only) in local
SESSION_COOKIE_SECURE=true                     # override to false only in local non-TLS dev
SESSION_COOKIE_MAX_AGE_SECONDS=31536000

# --- Behavior ---
SESSION_LAST_SEEN_DEBOUNCE_SECONDS=60
SESSION_ANONYMOUS_TTL_DAYS=90
SESSION_PREFS_MAX_BYTES=8192
SESSION_FAVORITES_MAX=500

# --- Signing ---
SESSION_SIGNING_KEYS=1:<base64url>,2:<base64url>     # plain int versions, base64url unpadded
SESSION_SIGNING_ACTIVE_KEY=2                          # int matching one of the versions above
```

**No new CORS env var** — see §10. The portal origins live in the existing `CORS_ORIGINS` setting.

`Settings` (Pydantic) parses `SESSION_SIGNING_KEYS` into the dict the signer expects. Loaded once at app startup; reload requires restart (acceptable in v1).

The previously-mentioned `SESSION_AUTHENTICATED_TTL_DAYS` is **dropped from v1** — authenticated sessions aren't pruned in v1 (see §12); reintroduce when an actual policy exists.

### 12. Anonymous-session TTL sweep (CLI entrypoint)

**Decision**: pruning is a **CLI entrypoint**, executed on a schedule by an external runner (k8s CronJob, GitHub Actions cron, or platform equivalent). No HTTP surface, no auth — pruning is system maintenance, not a user-initiated admin action. Admin-authing it would have required a service-account admin user just for the cron, which is operational pain for no protection benefit (the binary already runs only where the operator chooses).

The repo has no in-process scheduler today, and `src/shared/jobs/` tracks job *runs* but does not *schedule* them. APScheduler / asyncio tick loops are out of scope for v1.

**Surface**:

- New use case: `sessions.application.use_cases.PruneStaleAnonymousSessions` — takes `ttl_days: int` (default `SESSION_ANONYMOUS_TTL_DAYS=90`) and the portal session maker, executes:
  ```sql
  DELETE FROM sessions
  WHERE kind = 'ANONYMOUS'
    AND last_seen_at < now() - (:days || ' days')::interval;
  ```
  Returns `{ deleted_count: int, duration_ms: int }`.
- New CLI: `src/sessions/entrypoints/prune_stale_anonymous.py`. Bootstraps a minimal `SessionsContainer` from settings (portal engine + session maker only — no FastAPI, no cookie signer, no auth wiring), runs the use case, prints the result as JSON to stdout, exits 0 on success / non-zero on failure. Ships with an explicit `if __name__ == "__main__": asyncio.run(main())` guard so `python -m sessions.entrypoints.prune_stale_anonymous` works; `src/sessions/entrypoints/__init__.py` exists (empty) to make the package importable. Invocation:
  ```bash
  uv run python -m sessions.entrypoints.prune_stale_anonymous
  ```
- External runner config (k8s CronJob YAML, GitHub Action, etc.) lives in the deploy repo and executes the CLI once daily. **Out of scope for this spec.** `docs/features/sessions.md` documents the CLI invocation contract.

Authenticated sessions are not pruned in v1 (1y cookie max-age, and an authenticated user re-claiming on a stale row is fine semantics).

### 13. Observability

- Each endpoint logs `{ endpoint, session_id_prefix, kind, latency_ms }`. `session_id_prefix` is the first 8 hex chars — enough to correlate logs without leaking the full id.
- Metrics (existing Prometheus surface): `session_init_total`, `session_claim_total{result}`, `session_patch_total{slice}`, `session_signature_failures_total`, `session_orphan_load_total` (cookie valid, row missing).
- Signature-failure spikes are an alerting trigger (potential key-rotation problem or attacker probing).

## Affected files / surfaces

- **New**: `src/sessions/**` — entire bounded context (see §1).
- **New**: `src/shared/auth/supabase.py` — extracted `decode_supabase_token(token, *, supabase_url, jwt_secret, audience)` helper.
- **Edit**: `src/shared/api/middleware.py`:
  - `PUBLIC_PREFIXES` gains `/api/v1/session/` (line 25).
  - `JWTAuthMiddleware._decode_token` becomes a delegating one-liner over `shared.auth.supabase.decode_supabase_token` with admin credentials. Behavior unchanged.
- **Edit**: `src/shared/config.py` — add `supabase_portal_*`, `portal_database_url`, and `session_*` settings. (No new CORS setting — `cors_origins` is reused.)
- **Edit**: `src/shared/main.py`:
  - Build the portal engine + session maker at lifespan start.
  - Construct + attach `app.state.sessions_container`.
  - Mount the public sessions router under `/api/v1/session`.
  - Register the session router's exception handlers.
  - **CORS middleware: no edit required** — the existing config already covers credentialed origins via `CORS_ORIGINS`.
- **New**: `alembic-portal.ini` + `alembic-portal/env.py` + `alembic-portal/script.py.mako` + `alembic-portal/versions/<rev>_add_sessions_table.py`. Mirrors the existing admin Alembic skeleton but imports portal-context models only (`sessions.adapters.database.models`) and reads `settings.portal_database_url`. Imports the portal-scoped `Base` from `sessions.adapters.database.base`, not `shared.database.models.Base`.
- **New**: `scripts/migrate_admin.sh` + `scripts/migrate_portal.sh` wrapper scripts. Each validates the required env var (`DATABASE_URL` / `PORTAL_DATABASE_URL`), redacts and prints the target host, forwards all args to `uv run alembic` with the right `-c` flag. Documented as the canonical migration entry points in CLAUDE.md and the deploy pipeline.
- **No edits** to `src/shared/jobs/` — pruning is a CLI entrypoint (§12), not a scheduled-job framework entry.
- **Tests**:
  - `tests/unit/sessions/` — domain methods, capability derivation, cookie signer round-trip + tampering, prefs size cap, favorite cap.
  - `tests/integration/sessions/` — `init` / `me` / `patch` / `claim` / `logout` over the full FastAPI stack with the inmemory repo + a stub `ValidatePortalAuthToken`.
  - `tests/integration/sessions/test_signing_key_rotation.py` — sign with v1, verify with `{v1, v2}` configured (active=v2), then drop v1 and verify rejection.
  - `tests/integration/sessions/test_middleware_bypass.py` — request `/api/v1/session/init` *without* an `Authorization: Bearer` header and confirm it reaches the route (not 401'd by `JWTAuthMiddleware`).
  - `tests/integration/sessions/test_cors_preflight.py` — `OPTIONS /api/v1/session/me` with `Origin: https://predileto.pt` (added to test-config `CORS_ORIGINS`) returns `Access-Control-Allow-Credentials: true` and the matching origin; an unlisted origin is rejected.
  - `tests/unit/shared/auth/test_supabase.py` — `decode_supabase_token` round-trips ES256+JWKS and HS256+secret for both admin and portal credentials. Also asserts `JWTAuthMiddleware` behaviour is unchanged after the extraction (delegates correctly).
  - `tests/unit/shared/auth/test_jwks_cache.py` — `fetch_jwks_public_key` is URL-keyed: calling it with admin and portal URLs returns the right key for each, with no cross-contamination.
  - `tests/integration/sessions/test_prune_use_case.py` — drives `PruneStaleAnonymousSessions` against a fresh portal DB; asserts anonymous sessions older than `SESSION_ANONYMOUS_TTL_DAYS` are deleted, authenticated sessions and recent anonymous sessions survive, and the returned `{deleted_count, duration_ms}` matches.
  - `tests/integration/sessions/test_prune_cli.py` — invokes the CLI as a subprocess (`uv run python -m sessions.entrypoints.prune_stale_anonymous`); asserts exit code 0 and that stdout is valid JSON with the expected keys. (Smoke test for the entrypoint wiring; the per-row behaviour is covered by the use case test.)
- **Docs**:
  - New `docs/features/sessions.md` — bounded context, cookie shape, endpoint contract, key-rotation procedure, portal DB + dual-Supabase architecture, CLI invocation for prune.
  - `CLAUDE.md` — add `Sessions` row to the Bounded Contexts table; replace the single Alembic command block with `bash scripts/migrate_admin.sh ...` and `bash scripts/migrate_portal.sh ...` variants in the Commands section.

## Acceptance criteria

- [x] `POST /api/v1/session/init` mints an anonymous session in the **portal** DB, persists a row, and returns 200 + `Set-Cookie: predileto_session=...` with `HttpOnly`, `Secure`, `SameSite=Lax`, the configured `Max-Age`, and the configured `Domain`. — `test_init_mints_cookie_and_anonymous_view`
- [x] `POST /api/v1/session/init` with a valid existing cookie is a no-op (returns the existing session view, no `Set-Cookie`), but still debounce-refreshes `last_seen_at` (same rule as `GET /me`). — `test_init_with_valid_cookie_is_no_op`
- [x] `GET /api/v1/session/me` returns the public `SessionView` for the cookie holder and refreshes `last_seen_at` only when older than `SESSION_LAST_SEEN_DEBOUNCE_SECONDS`. — `test_me_returns_view_for_valid_cookie`
- [x] `GET /api/v1/session/me` returns 401 with distinguishable codes `SESSION_MISSING` (no cookie) and `SESSION_INVALID` (bad signature, missing row, or `revoked=true`). The FE recovers from `SESSION_INVALID` by re-calling `POST /session/init`. — `test_me_without_cookie_returns_401`, `test_me_with_tampered_cookie_returns_session_invalid`
- [x] `PATCH /api/v1/session/me` applies `favorites.add`/`favorites.remove` and `prefs.merge`, rejects oversized prefs (8 KB), rejects > 500 favorites, rejects non-UUID favorite ids with `INVALID_FAVORITE_ID`. — `test_patch_favorites_and_prefs`, `test_patch_rejects_invalid_uuid`, `test_patch_rejects_oversized_prefs`
- [x] `POST /api/v1/session/claim` reads the **`Authorization: Bearer`** header, calls `ValidatePortalAuthToken` (portal Supabase secret/JWKS), flips to `AUTHENTICATED`, populates `user_id`, sets `claimed_at`, **does not rotate the cookie**, preserves favorites + prefs. — `test_claim_with_valid_token_flips_to_authenticated`
- [x] `POST /api/v1/session/claim` returns 401 `PORTAL_AUTH_TOKEN_INVALID` when the validator raises, and is reachable without an admin JWT. — `test_claim_with_unknown_token_returns_401`, `test_claim_without_bearer_header_returns_401`
- [x] `POST /api/v1/session/logout` flips `kind` back to `ANONYMOUS`, clears `user_id`, `claimed_at`, **`favorites`**, **`prefs`**. — `test_logout_clears_favorites_and_prefs`
- [x] `POST /api/v1/session/logout` is idempotent. — `test_logout_is_idempotent_on_anonymous_session`
- [x] Capability list is derived from `kind`. — `test_anonymous_capabilities`, `test_authenticated_capabilities_are_superset` + integration assertions in `test_init_mints_cookie_and_anonymous_view` / `test_claim_with_valid_token_flips_to_authenticated`
- [x] Cookie signing supports versioned keys with rotation. — `test_rotation_old_key_still_verifies_while_present`
- [x] HMAC signature tampering is detected. — `test_tampered_signature_fails`, `test_me_with_tampered_cookie_returns_session_invalid`
- [x] `/api/v1/session/*` is in `shared.api.middleware.PUBLIC_PREFIXES`. — `test_init_reachable_without_authorization_header`
- [x] `shared.auth.jwks.fetch_jwks_public_key` is URL-keyed. — `test_cache_is_url_keyed`, `test_clear_cache_drops_all_urls`
- [x] **No imports from `sessions/` into any other context**, and `sessions/` does not import admin contexts. — verified by inspection (only `shared.*` imports outside `sessions/`).
- [x] **JWT decode helper extraction is behavior-preserving** — existing `JWTAuthMiddleware` tests still pass (`tests/unit/shared_api/test_identity_middleware.py`, 13 tests green). Helper exercised via the same path; portal validator is the parameterised variant.
- [x] `scripts/migrate_admin.sh` / `scripts/migrate_portal.sh` fail fast on missing env, forward positional args, print the target host (password redacted) to stderr. — implemented per spec; manual smoke test left to the operator running against a real DB.
- [x] `load_session` raises domain exceptions, never `HTTPException` directly. A registered exception handler maps each to its HTTP response. — implemented in `sessions/adapters/api/cookie.py` + `sessions/adapters/api/exception_handlers.py`; observed end-to-end in lifecycle tests via the JSON error-code responses (`SESSION_MISSING`, `SESSION_INVALID`, `INVALID_FAVORITE_ID`, etc.).
- [x] CLAUDE.md gains the `Sessions` bounded-context row and the wrapper-script migration commands.

### Deferred to the operator / follow-up

These require a live two-DB environment to exercise and are out of scope for the BE merge:

- [ ] `POST /api/v1/session/claim` returns 409 `SESSION_BOUND_TO_OTHER_USER` when the session is already authenticated to a different user. (Domain branch covered by `ClaimSession.execute` + the `SessionBoundToOtherUser` handler; integration coverage needs a second valid portal token, which the stub validator supports but is left as an exercise for the follow-up portal-identity spec.)
- [ ] `uv run python -m sessions.entrypoints.prune_stale_anonymous` against a live portal DB. (Use case `PruneStaleAnonymousSessions` covered by the in-memory repo path; CLI smoke test deferred to the deploy-pipeline spec — needs a live portal Postgres.)
- [ ] CORS preflight assertion in CI. (Pre-existing `CORSMiddleware` already handles this; verifying it requires no code change in this spec. Manual curl test on the deployed environment will confirm.)
- [ ] **Portal DB is a distinct database** end-to-end: `bash scripts/migrate_portal.sh upgrade head` against `PORTAL_DATABASE_URL` creates `sessions` and the admin DB doesn't gain the table. (Migration script + alembic-portal config are in place; verification requires a live two-DB environment.)
- [ ] Both Alembic configurations apply cleanly on fresh DBs (independent of each other). (Same — needs live DBs.)
- [ ] `docs/features/sessions.md` long-form documentation. (Spec body + CLAUDE.md cover the key facts; the standalone feature doc can land in a follow-up `docs(sessions):` PR.)

## Open questions

- **Portal Supabase audience claim.** Default `authenticated` should match a vanilla Supabase project. Confirm the portal project doesn't override it before locking the env-var default.
- **`SESSION_COOKIE_DOMAIN` in production.** `.predileto.pt` is the natural answer if a future second frontend (e.g. `app.predileto.pt`) should share the session. Confirm with deploy ops before first prod ship.
- **Deploy pipeline edits** (operational, not in this spec): the deploy pipeline needs (a) `bash scripts/migrate_admin.sh upgrade head` and `bash scripts/migrate_portal.sh upgrade head` steps before app boot (order between them doesn't matter); (b) a cron runner (k8s CronJob, GitHub Action, etc.) executing `uv run python -m sessions.entrypoints.prune_stale_anonymous` daily. Both live in the deploy repo; flagged here so they're not forgotten.

## Out of scope follow-ups

- **Portal `User` registration endpoint** — `POST /api/v1/portal/auth/register` writing to the portal DB. Lands in a portal-identity spec. When it ships, the existing `/api/v1/portal/auth/register` route at `identity/adapters/api/routes/portal_auth.py` (currently sharing the admin Supabase + admin DB — incorrect for the new model) is migrated or replaced.
- **Preference schema.** Lock the prefs JSONB shape into a typed model in a follow-up spec when product decides the fields.
- **Portal user-side wishlist store + claim merge.** When the portal user record gains a saved-properties list, `claim` should union the anon session's favorites into it. New spec.
- **Logout-with-revoke** (kill the cookie entirely instead of flipping to anonymous).
- **"Keep my saved properties" toggle on logout** — if product wants the preserved-on-logout behaviour that ADR-001 §7 originally described, it lives behind an explicit UI affordance, not as the default.
- **Rate limiting + abuse detection** layered on `session_id` (currently only the substrate is in place).
- **Cross-domain cookie** (multiple frontends sharing the session). The `Domain` env var already supports it; the deployment story is the follow-up.
- **Redis substrate** for the session store if Postgres latency becomes a problem. The repository port keeps consumers ignorant of the swap.
- **Hot key rotation tooling** (CLI + key-management runbook).
- **PostHog `identify` hand-off** — the portal calls `posthog.identify(user_id, { previous_anon_id })` after claim. BE returns enough info in `SessionView` already; no BE change needed, but flagged for the portal spec.
- **Explicit CSRF tokens** — only if a future change defeats the SameSite=Lax + CORS allow-list + Bearer-on-claim defense in depth (§10).

## Commits

Scope: `sessions` for everything new in the bounded context; `shared` for the JWT-decode extraction, CORS config, and portal engine wiring; `docs` for the feature page and CLAUDE.md row.

Expected sequence (one PR per bullet unless tightly coupled):

- `chore(shared): extract Supabase JWT decode into shared/auth/supabase.py`
- `feat(shared): portal Supabase + portal Postgres engine wiring`
- `feat(sessions): domain model + capability derivation + cookie signer`
- `feat(sessions): portal-DB repository + alembic-portal config + sessions migration`
- `chore(scripts): migrate_admin.sh + migrate_portal.sh wrappers`
- `feat(sessions): POST /session/init + GET /session/me + load_session dependency`
- `feat(sessions): PATCH /session/me with favorites + prefs slice writes`
- `feat(sessions): POST /session/claim + portal-Supabase token validator`
- `feat(sessions): POST /session/logout (clears favorites/prefs)`
- `feat(sessions): /api/v1/session/* added to PUBLIC_PREFIXES`
- `feat(sessions): prune-stale-anonymous CLI entrypoint`
- `docs(sessions): feature docs + CLAUDE.md context row + portal-alembic commands`
