# Subscriptions v1 — Stripe Checkout + Customer Portal

**Status:** in-progress
**Owner:** Peter
**Created:** 2026-04-19

## Problem

Estate-OS needs live billing before launch. The Organizations context already carries a `Subscription` aggregate with Stripe-shaped fields (`stripe_subscription_id`, `stripe_price_id`, `status`, `current_period_*`), but **no Stripe integration exists** — `grep -rn stripe src/` returns zero hits. The frontend `dashboard/settings/subscriptions` page is a static mock with hard-coded EUR prices and no upgrade path.

Without billing, every new organization is effectively free forever. Launch is blocked on:
1. A way for owners/admins to subscribe to a paid plan.
2. A way for them to self-serve cancel / change plan / update card / pull invoices.
3. Our DB reflecting the true state of Stripe (active / trialing / past due / cancelled), driven by webhook events.

## Goal

Owners and admins of an organization can start a 7-day trial on Pro or Enterprise (monthly or yearly) from `/dashboard/settings/subscriptions`, complete payment on Stripe-hosted Checkout, return to a chrome-free confirmation page, and from then on manage everything (cancel, change plan, update card, invoices) through Stripe Customer Portal — with our `Subscription` row always reconciled to Stripe via signed webhooks.

## Non-goals

- Per-seat or usage-based billing (metered pricing).
- Custom in-app UI for cancel / plan switch / invoice history (Portal owns those).
- Stripe Tax integration.
- Customised Stripe email receipts (Resend templates).
- Proration preview UX in-app.
- Plan downgrade grace-period flows beyond whatever the Portal defaults to.
- Freemium gating inside the product (what features are blocked on Free) — that's a separate enforcement spec.

## Approach

### Plans & authz (decisions)

- **Plans:** `Pro` + `Enterprise`, each with monthly and yearly recurring prices. `Freemium` remains the default seeded plan on org creation, with no Stripe objects.
- **Who can manage billing:** `OWNER` and `ADMIN` roles. `MEMBER` is read-only.
- **Self-service:** Stripe Customer Portal for all post-checkout actions.
- **Trial:** 7-day trial on paid plans, via `trial_period_days` on Checkout session.

### Flow diagram

```
Admin → /dashboard/settings/subscriptions
  ├── (no sub) click "Start free trial" (Pro monthly)
  │     → POST /api/v1/admin/billing/checkout {plan, cadence}
  │     → backend creates Stripe Customer if needed, Checkout Session
  │     → returns {url}
  │     → window.location.href = url
  │     → Stripe-hosted Checkout collects card
  │     → success → /billing/return?session_id=... (bare page)
  │       → polls GET /api/v1/admin/billing/subscription
  │       → once TRIALING+stripe_subscription_id set → redirect to settings/subscriptions?welcome=1
  │     (async) Stripe → POST /api/v1/billing/webhooks/stripe
  │                    → checkout.session.completed / subscription.created
  │                    → HandleStripeWebhookEvent updates Subscription row
  │
  └── (has sub) click "Manage billing"
        → POST /api/v1/admin/billing/portal
        → returns {url} (Stripe Portal session)
        → redirect; user cancels / changes plan / updates card / views invoices
        → returns to /dashboard/settings/subscriptions
        (async) Stripe webhook syncs every state change
```

### Layering (hexagonal, existing conventions)

**Port:** `src/organizations/application/ports/billing_gateway.py`

```python
class BillingGateway(Protocol):
    async def create_customer(self, *, org_id: UUID, email: str, name: str) -> str: ...
    async def create_checkout_session(self, *, customer_id: str, price_id: str,
        success_url: str, cancel_url: str, trial_days: int) -> CheckoutSession: ...
    async def create_portal_session(self, *, customer_id: str, return_url: str) -> str: ...
    def verify_webhook(self, *, payload: bytes, signature: str) -> StripeEvent: ...
```

**Adapter:** `src/organizations/adapters/outbound/stripe/billing_gateway.py` — Stripe Python SDK, blocking calls wrapped in `asyncio.to_thread`.

**Test double:** `src/organizations/adapters/inmemory/billing_gateway.py` — deterministic, records calls; constructs `StripeEvent` objects for tests.

**Idempotency:** new `stripe_webhook_events` table (`event_id PK`, `processed_at`). `HandleStripeWebhookEvent` checks before mutating; duplicate = no-op ack.

### Event handling

Webhook route → verify signature → look up by `event.id` (skip if seen) → dispatch:

| Stripe event | Subscription action |
|---|---|
| `checkout.session.completed` | Upsert: set `stripe_customer_id`, `stripe_subscription_id`, `stripe_price_id`, derive `plan` from price-ID map, `type=STRIPE`, `status` from Stripe |
| `customer.subscription.updated` | Sync `status`, `current_period_start/end`, `stripe_price_id`, `plan` |
| `customer.subscription.deleted` | `status = CANCELLED` |
| `invoice.payment_failed` | `status = PAST_DUE` |
| `invoice.paid` | If `PAST_DUE`, flip back to `ACTIVE` |
| other | Log, ack 200 |

### Authz & middleware

- New `require_org_admin` dependency in `src/shared/api/dependencies.py` — extends `require_org_member`, enforces `membership.role in {OWNER, ADMIN}` else 403.
- `JWTAuthMiddleware` and `IdentityMiddleware` skip `/api/v1/billing/webhooks/*` — Stripe posts unauthenticated (signature auth only).

### Frontend layout refactor

Today's root layout (`src/app/layout.tsx`) mounts `SidebarProvider/AppSidebar/MainHeader` conditionally on auth. Next.js layouts only *add* chrome to children, so a chrome-free checkout page can't exist under this root. Fix:

- **Root `layout.tsx`:** strip Supabase check + sidebar/header. Providers only.
- **New `dashboard/layout.tsx`:** hosts the Supabase check + `SidebarProvider/AppSidebar/MainHeader/SidebarInset`. All existing dashboard routes inherit chrome exactly as before.
- New `/billing/return` and any future billing pages are bare by default.

### Stripe sandbox setup (operator runbook)

See `docs/runbooks/stripe-sandbox-setup.md` (created by this spec). Summarised:

1. Create Products **Pro** and **Enterprise** in Test mode, each with monthly + yearly recurring EUR prices (€29 / €290, €99 / €990).
2. Copy the 4 `price_*` IDs into backend config.
3. Create webhook endpoint at `{API_URL}/api/v1/billing/webhooks/stripe` subscribed to:
   `checkout.session.completed`, `customer.subscription.{created,updated,deleted}`, `invoice.{paid,payment_failed}`. Copy signing secret.
4. Enable Customer Portal with cancel / switch plan (across the 4 prices) / update card / invoices. Return URL = `{APP_URL}/dashboard/settings/subscriptions`.
5. For local dev: `stripe listen --forward-to http://localhost:8000/api/v1/billing/webhooks/stripe`.

## Affected files / surfaces

### Backend (`estate-os-service`)

**Config + infra:**
- `src/shared/config.py` — add `stripe_api_key`, `stripe_webhook_secret`, 4× `stripe_price_*`, `stripe_trial_period_days`, 3× billing redirect URLs.
- `src/shared/api/middleware.py` — exempt webhook path from JWT + identity middleware.
- `src/shared/api/dependencies.py` — new `require_org_admin`.
- `src/shared/main.py` — mount billing router.
- `src/shared/entrypoints/bootstrap.py` — wire `StripeBillingGateway`.
- `pyproject.toml` — add `stripe ^10.0`.

**Organizations domain + DB:**
- `src/organizations/domain/models/subscription.py` — add `stripe_customer_id`.
- `src/organizations/adapters/database/models.py` — column + partial index.
- `alembic/versions/20260419_*_add_stripe_billing.py` — add `stripe_customer_id` column, create `stripe_webhook_events` idempotency table.

**New billing module:**
- `src/organizations/application/ports/billing_gateway.py`
- `src/organizations/application/ports/stripe_webhook_events_repo.py`
- `src/organizations/adapters/outbound/stripe/billing_gateway.py`
- `src/organizations/adapters/inmemory/billing_gateway.py`
- `src/organizations/adapters/inmemory/stripe_webhook_events_repo.py`
- `src/organizations/adapters/database/stripe_webhook_events_repo.py`
- `src/organizations/application/use_cases/billing/start_checkout_session.py`
- `src/organizations/application/use_cases/billing/start_billing_portal_session.py`
- `src/organizations/application/use_cases/billing/handle_stripe_webhook.py`
- `src/organizations/application/use_cases/billing/price_id_map.py` (small helper)
- `src/organizations/adapters/inbound/billing_routes.py`
- `src/organizations/container.py` — inject gateway + webhook repo + new use cases.

**Tests:**
- `tests/unit/organizations/billing/test_start_checkout_session.py`
- `tests/unit/organizations/billing/test_start_billing_portal_session.py`
- `tests/unit/organizations/billing/test_handle_stripe_webhook.py`
- `tests/unit/shared/test_require_org_admin.py`
- `tests/database/test_stripe_webhook_events_repo.py`
- `tests/database/test_subscription_repo.py` — extend for `stripe_customer_id`
- `tests/integration/test_billing_routes.py`

**Docs:**
- `docs/runbooks/stripe-sandbox-setup.md` — Stripe dashboard checklist.
- `docs/features/organizations.md` — append billing section if it exists.

### Frontend (`estate-os`)

**Layout refactor:**
- `src/app/layout.tsx` — strip chrome, keep providers only.
- `src/app/dashboard/layout.tsx` — add Supabase check + chrome components.

**New / rewritten pages + client:**
- `src/app/billing/return/page.tsx` — new bare page.
- `src/app/dashboard/settings/subscriptions/page.tsx` — rewrite (server fetch, client toggle, CTAs).
- `src/app/dashboard/settings/subscriptions/subscriptions-client.tsx` — new client component for toggle + buttons.
- `src/lib/api/billing.ts` — new thin wrappers over core-client.
- `src/dictionaries/pt.json`, `en.json` — new strings.

**Tests:**
- `src/__tests__/app/dashboard/settings/subscriptions.test.tsx`
- `src/__tests__/app/billing/return.test.tsx`
- `cypress/e2e/billing.cy.ts`

## Acceptance criteria

- [ ] Owners and admins can open Stripe Checkout from the subscriptions page and complete a test checkout with card `4242 4242 4242 4242`.
- [ ] After checkout, user lands on `/billing/return?session_id=...` (no sidebar, no header) and is redirected to `/dashboard/settings/subscriptions?welcome=1` once the webhook lands.
- [ ] `Subscription` row reflects `TRIALING` + correct `plan`, `stripe_customer_id`, `stripe_subscription_id`, `stripe_price_id`, `current_period_end` — sourced from webhook, not frontend.
- [ ] Yearly/monthly toggle swaps which price ID the Checkout uses (Stripe confirms the correct price on the hosted page).
- [ ] Customer Portal button (visible only for active subscriptions) opens the hosted portal and returns to the subscriptions page on close.
- [ ] Cancelling via the Portal flips the row to `CANCELLED` within ~5s (webhook-driven).
- [ ] `invoice.payment_failed` webhook flips row to `PAST_DUE`; follow-up `invoice.paid` restores `ACTIVE`.
- [ ] `MEMBER` role sees the page but has no Upgrade / Manage Billing buttons. Direct `POST /api/v1/admin/billing/checkout` returns 403.
- [ ] Webhook endpoint rejects requests with an invalid `Stripe-Signature` (400).
- [ ] Replaying the same Stripe `event.id` is a no-op on the DB (idempotency table).
- [ ] Tests:
  - unit: every webhook transition, both checkout/portal use cases, `require_org_admin`
  - database: `stripe_customer_id` round-trip, webhook-events repo
  - integration: all 4 billing routes (including 403/401 role matrix and signature rejection)
  - frontend jest: toggle swap, role-gated buttons, return-page polling success + timeout
  - cypress: admin checkout happy path, return-page redirect, member role hides buttons
- [ ] `ruff check` and `ruff format --check` pass; `npm run lint` passes in `estate-os`.
- [ ] Migration applies cleanly on fresh DB (`uv run alembic upgrade head`).
- [ ] `docs/runbooks/stripe-sandbox-setup.md` is complete enough to set up a fresh Stripe test account end-to-end.

## Open questions

- Should `organizations.Organization.created_by` email be the Checkout customer email, or the currently-acting admin's email? **Working assumption:** the acting admin's email (`request.state.user.email`). Stripe records this on the customer; we can change later.
- How do we back-populate `stripe_customer_id` on existing Free orgs when they first upgrade? **Working assumption:** lazily — `StartCheckoutSession` creates the Stripe customer on first use if `stripe_customer_id` is null, then persists it.

## Out of scope follow-ups

- Feature gating by plan (what does Free lose?) — separate spec.
- Stripe Tax / VAT collection — separate spec.
- Email notifications on payment failure (Resend template) — separate spec.
- Seat-based pricing — separate spec.
- Plan downgrade / cancellation retention flow UX — separate spec.
- Backfill script for orgs created before billing launched.
