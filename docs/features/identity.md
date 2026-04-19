# Identity

The `identity` bounded context owns the `User` aggregate — authenticated users backed by Supabase auth. It's the entry point for anyone interacting with the service: admins (agency staff) and portal users (applicants) both resolve to the same `User` class. "Admin-ness" is not a User field; it's derived from membership state (see `organizations`).

**Source:** `src/identity/`

## Domain entity

| Entity | Description |
|--------|-------------|
| `User` | Supabase-backed identity. Fields: `id`, `supabase_user_id`, `email`, `name`, `phone: PhoneNumber \| None`, `google_metadata`, timestamps. **No `organization_id`** — tenancy lives in `organizations.Membership`. |

Value objects: `PhoneNumber` (at `src/identity/domain/value_objects.py`).

## Cross-context ports (callable Protocols)

Per [ADR / spec: identity-context-split-and-membership-auth](../../.claude/specs/archive/2026-04-identity-context-split-and-membership-auth.md#q1--protocol--use-case-method-naming), `organizations` consumes identity via two callable Protocols — both bound at container-construction time to identity's use-case methods. No adapter classes; duck-typing is sufficient.

- `UserLookupById(Protocol): async __call__(id: UUID) -> User | None` — bound to `FindUser.by_id`.
- `RegisterUserPort(Protocol): async __call__(*, supabase_user_id, email, name, phone?, google_metadata?) -> User` — bound to `RegisterUser.execute`.

Identity does **not** import from organizations. Enforced by acceptance criterion `grep -rn "from organizations" src/identity/` → zero hits.

## Use cases

| Use case | Purpose |
|---|---|
| `RegisterUser` | Create a User. **Idempotent on `supabase_user_id`** — duplicate sub returns the existing row, not a 409. Used directly by `POST /api/v1/portal/auth/register` and indirectly by `organizations.RegisterAdminAccount` via the `RegisterUserPort` binding. |
| `UpdateUserProfile` | Update `name` and/or `phone`. Served by `PATCH /auth/profile`. |
| `FindUser` | Two methods: `by_id(id)` (bound as `UserLookupById`) and `by_supabase_id(supabase_user_id)` (called directly by `IdentityMiddleware` — shared infrastructure can bypass the Protocol layer per Q2 = 2.b). |

## HTTP routes

Routes live at `src/identity/adapters/api/routes/`. `/auth/me` + `/auth/profile` are mounted under both `/api/v1/admin` and `/api/v1/portal`; the admin-prefix mount naturally 403s for a user without memberships via the `IdentityMiddleware` rule.

| Path | Method | Handler |
|---|---|---|
| `/api/v1/portal/auth/register` | POST | Create User (idempotent on `supabase_user_id`). |
| `/api/v1/admin/auth/me`, `/api/v1/portal/auth/me` | GET | Return `{user, memberships: [...]}` from `request.state`. No DB calls — data populated by `IdentityMiddleware`. |
| `/api/v1/admin/auth/profile`, `/api/v1/portal/auth/profile` | PATCH | Update profile. |

Admin registration lives in `organizations` (see below) — it's a compound use case and doesn't belong in identity.

## Adapters

Dual-adapter pattern (preserved from the pre-split `customers` context):

- `src/identity/adapters/persistence/supabase_user_repo.py` — PostgREST via `supabase-py` AsyncClient (production).
- `src/identity/adapters/database/user_repo.py` — SQLAlchemy async (tests).
- `src/identity/adapters/database/models.py` — SQLAlchemy `UserModel` (owns the `users` table).
- `src/identity/adapters/inmemory/inmemory_user_repo.py` — in-memory test double.

## Container

`src/identity/container.py` wires `FindUser`, `RegisterUser`, `UpdateUserProfile` over a `UserRepository`. Exposes two callable bindings for cross-context injection: `register_user_port` and `user_lookup_by_id`.

## Registration semantics (idempotency + retry)

`RegisterUser.execute(supabase_user_id=..., ...)`:

- First call with a fresh `supabase_user_id` → creates a User row, returns it.
- Duplicate `supabase_user_id` → **returns the existing row** without error.
- Email / name arguments on the second call are **ignored** — the existing row is returned unchanged.

This idempotency is what makes `POST /api/v1/admin/auth/register` safe to retry: if the downstream Org/Membership/Subscription transaction fails, the caller can re-submit and step 1 no-ops. See `organizations.RegisterAdminAccount` for the full flow.
