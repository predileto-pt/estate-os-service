# Organizations

The `organizations` bounded context owns tenancy: `Organization`, `Membership`, `Invitation`, `Notification`. Identity was extracted to its own context (`identity`) — organizations holds "what you can do", identity holds "who you are". Billing (Subscription, Stripe, Checkout, Portal, webhooks) was extracted to the `billing` context — see [billing.md](./billing.md).

**Source:** `src/organizations/`

## Domain entities

| Entity | Description |
|---|---|
| `Organization` | Tenant. Has one Subscription (owned by `billing`) and many members. |
| `Membership` | User↔Organization link with a role (`OWNER`, `ADMIN`, `MEMBER`). **Source of truth for admin access** — if a user has no memberships, they're a portal user. |
| `Invitation` | Pending email invite with 7-day expiry. Status: `PENDING` / `ACCEPTED` / `EXPIRED` / `REVOKED`. |
| `Notification` | In-app notification. Status: `UNREAD` / `READ`. |

Internal mirror: `organizations.domain.models.user.User` — same shape as `identity.User` (sans `organization_id`). Used by membership/invitation use cases that look up users by email/id through the org-side `UserRepository` port. Keeps the business layer from importing identity's domain class.

Value objects: `Address` (at `src/organizations/domain/value_objects.py`). `PhoneNumber` lives in `identity`.

Authorization rules: `src/organizations/domain/models/authorization.py` — `has_permission(role, codename)` over a static `ROLE_PERMISSIONS` dict. (Currently informational — `IdentityMiddleware` uses "has any membership" as the admin gate; role-based capabilities are a follow-up.)

## Cross-context dependency

`organizations` depends on `identity` via two callable Protocols injected at container construction — no direct imports of identity's domain class or use-case classes from business code.

- `UserLookupById` (consumed by future renderer use cases — not yet wired in a production call site).
- `RegisterUserPort` (consumed by `RegisterAdminAccount` — see below).

Enforcement: `grep -rn "from identity" src/organizations/` → three expected sites only (`application/use_cases/register_admin_account.py`, `adapters/api/routes/admin_auth.py`, and `container.py`).

## Compound registration — `RegisterAdminAccount`

Admin registration is a three-step use case; portal registration lives in `identity` and is a single call.

`POST /api/v1/admin/auth/register` → `RegisterAdminAccount.execute`:

1. **Identity step (identity-local tx).** Call `identity.register_user` via the `RegisterUserPort` binding. Idempotent on `supabase_user_id` — returns the existing User on retry.
2. **Duplicate-account check.** `membership_repo.list_by_user(user.id)` — if non-empty, raise `AdminAccountAlreadyExistsError` (HTTP 409). Rules out blind retries after prior success and portal-user promotes trying to sneak through admin registration.
3. **Organizations step (org-local + cross-context billing seed).** Create `Organization` + `OwnerMembership`. On a fresh org (not an invitation acceptance), call `billing.seed_freemium_subscription_port(organization_id=...)` to create the default Subscription. If a pending invitation exists, the user joins the invited org instead of creating a new one — the invitation is marked `ACCEPTED` and no billing seed is triggered (the existing org already has its own Subscription).

Retry semantics: if step 3 fails, the User from step 1 is orphaned but safely retryable. On retry, step 1 no-ops, step 2 passes (orphan has no memberships), step 3 reruns. If the full flow already succeeded and the caller re-submits, step 2 hits 409 — no duplicate Org/Membership/Subscription.

## `MembershipRepository` — `list_by_user_id_with_org_names`

Projection returned by `MembershipRepository.list_by_user_id_with_org_names(user_id)` is a read-only `MembershipWithOrgName` (id, user_id, organization_id, role, **organization_name**, created_at, updated_at) — a single JOIN query. Used by `IdentityMiddleware` to populate `request.state.memberships` with org names, avoiding N+1 on `/auth/me` rendering. Three adapters implement it:

- SQLAlchemy: `select(MembershipModel, OrganizationModel.name).join(...)`.
- Supabase PostgREST: embedded resource `.select("*, organizations(name)")`.
- In-memory: optional `organization_repo` ref resolves names in-process.

## HTTP routes

| Path | Method | Handler |
|---|---|---|
| `/api/v1/admin/auth/register` | POST | `RegisterAdminAccount` (compound — user via `identity`, org + membership locally, subscription via `billing` callable port). |
| `/api/v1/admin/organizations/...` | GET/PATCH | Organization CRUD. |
| `/api/v1/admin/memberships/...` | GET/DELETE/PATCH | Membership management + role updates. |
| `/api/v1/admin/invitations/...` | GET/POST/DELETE | Invitation management. |
| `/api/v1/admin/billing/...` | GET/POST | Owned by `billing` — Checkout, Portal, plans. See [billing.md](./billing.md). |
| `/api/v1/billing/webhooks/stripe` | POST | Owned by `billing` — signature-authed webhook ingress. See [billing.md](./billing.md). |
| `/api/v1/admin/notifications/...` | GET/PATCH | In-app notifications. |
| `/api/v1/admin/email/...` | POST | Transactional email. |

## Adapters (per-aggregate split)

Same dual-adapter pattern as identity. Each aggregate has its own file:

- `src/organizations/adapters/persistence/supabase_*_repo.py` (prod).
- `src/organizations/adapters/database/repositories.py` (SQLAlchemy; hosts Organization / Notification / Membership / Invitation repos — Subscription moved to `src/billing/adapters/database/subscription_repository.py`).
- `src/organizations/adapters/database/models.py` (SQLAlchemy models).
- `src/organizations/adapters/inmemory/inmemory_*_repo.py` (test doubles).

## Container

`src/organizations/container.py` wires all org-side repositories + `RegisterAdminAccount` (which takes the `RegisterUserPort` callable from identity's container at construction time). No direct identity-use-case imports.
