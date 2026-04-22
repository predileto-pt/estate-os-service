# Billing

The `billing` bounded context owns the `Subscription` aggregate and the complete Stripe integration: Checkout, Customer Portal, webhook ingestion, idempotency store, and the price catalog. It is the single source of truth for "what plan is this org on?" — read by feature-gating code elsewhere, mutated only by billing's use cases in response to Stripe webhooks.

`billing` is one of two contexts that organizations depends on via a callable-Protocol port (the other is `identity`): `organizations.RegisterAdminAccount` calls `billing.seed_freemium_subscription_port` during compound admin registration to create the default freemium Subscription for a new org. Billing does not import from organizations.

**Source:** `src/billing/` — domain, ports (incl. `seed_freemium_subscription`), use cases, adapters (Stripe, in-memory, Supabase, SQLAlchemy), container, and HTTP routes.

Every Organization has exactly one Subscription, seeded via the cross-context port when the Organization is created. New orgs start on `FREEMIUM` with no Stripe objects.

## Plans, types, statuses

| Enum | Values | Meaning |
|---|---|---|
| `SubscriptionPlan` | `freemium`, `pro`, `enterprise` | What the org is entitled to. `freemium` is the seeded default; `pro` / `enterprise` require a Stripe subscription. |
| `SubscriptionType` | `manual`, `stripe`, `deposit` | How billing is managed. `manual` for the seeded freemium row; flipped to `stripe` on first successful checkout. `deposit` is reserved for future prepaid billing. |
| `SubscriptionStatus` | `active`, `trialing`, `past_due`, `cancelled`, `inactive` | Current billing health. Derived from Stripe's subscription status (see mapping below). |

## Lifecycle

The lifecycle is driven entirely by two classes of input: **admin-initiated actions** from the frontend (Checkout, Customer Portal) and **asynchronous Stripe webhooks** that reconcile our row with Stripe's source of truth.

```
  ┌────────────────────────────────────────────────────────────────────────┐
  │ State transitions (Subscription.status, Subscription.plan)             │
  │                                                                        │
  │   (new org)                                                            │
  │      │                                                                 │
  │      ▼                                                                 │
  │  freemium / active / manual                                            │
  │      │                                                                 │
  │      │ admin clicks "Start trial" → Checkout completes                 │
  │      │ (customer.subscription.created webhook)                         │
  │      ▼                                                                 │
  │  pro-or-enterprise / trialing / stripe                                 │
  │      │                                                                 │
  │      │ trial converts (customer.subscription.updated)                  │
  │      ▼                                                                 │
  │  pro-or-enterprise / active / stripe ◄────┐                            │
  │      │                                    │                            │
  │      │ invoice.payment_failed             │ invoice.paid (recovery)    │
  │      ▼                                    │                            │
  │  pro-or-enterprise / past_due / stripe ───┘                            │
  │      │                                                                 │
  │      │ customer.subscription.deleted (via Portal cancel, or dunning)   │
  │      ▼                                                                 │
  │  pro-or-enterprise / cancelled / stripe                                │
  └────────────────────────────────────────────────────────────────────────┘
```

`plan` changes independently of `status` whenever Stripe reports a different `price_id` — e.g. a Pro→Enterprise switch via the Customer Portal sends `customer.subscription.updated` and we re-derive `plan` from `PriceCatalog.plan_for(price_id)`.

## Flow — checkout to active subscription

Stripe-hosted Checkout is used for all upgrades. The app never sees a card number. The full round-trip:

```
Admin (OWNER or ADMIN)
  │
  │ clicks "Start 7-day free trial" on /dashboard/settings/subscriptions
  ▼
POST /api/v1/admin/billing/checkout  {plan, cadence}
  │   — require_current_org_admin reads memberships from request.state (set by IdentityMiddleware)
  │   — StartCheckoutSession: looks up Subscription, lazily creates Stripe Customer
  │     and persists stripe_customer_id if first upgrade, then opens a Checkout Session
  │     with trial_period_days=7
  │
  ◄ { url: "https://checkout.stripe.com/..." }
  │
Frontend: window.location.href = url  ──────────►  Stripe-hosted Checkout
                                                             │
                                                             │ card, 3DS, etc.
                                                             ▼
                                 ┌──────────── Success ──────┴── Cancel ─────────┐
                                 ▼                                                ▼
  redirect → /dashboard/settings/subscriptions?welcome=1           redirect → ?checkout=cancelled
      (welcome banner; page re-fetches current subscription)            (cancel banner; no state change)
                                 │
                                 │  Meanwhile, async:
                                 ▼
Stripe  ─── POST /api/v1/billing/webhooks/stripe  (Stripe-Signature header) ───►  app
                                                             │
                                                             │ verify_webhook, then:
                                                             ▼
                                              HandleStripeWebhookEvent
                                              → checkout.session.completed:
                                                   attach stripe_subscription_id
                                              → customer.subscription.created:
                                                   status=trialing, plan=<derived>
                                                   current_period_*, type=stripe
```

Because the success URL and the webhook race each other, the admin may briefly land on the subscriptions page showing the pre-webhook state (still `freemium / active / manual`). The welcome banner masks this; a refresh (or simply navigating away and back) shows the correct `trialing` state once the webhook lands (typically within ~1 s).

## Flow — self-service management

Once a Subscription has a `stripe_customer_id`, the "Manage billing" button is shown:

```
Admin clicks "Manage billing"
  │
  ▼
POST /api/v1/admin/billing/portal
  │   — StartBillingPortalSession: opens a Customer Portal session for stripe_customer_id
  │
  ◄ { url: "https://billing.stripe.com/..." }
  │
Frontend: window.location.href = url  ──────────►  Stripe Customer Portal
                                                             │
                                                             │ cancel / switch plan / update card / pull invoice
                                                             ▼
                                 redirect → /dashboard/settings/subscriptions
                                                             │
                                                             │  For every change:
                                                             ▼
Stripe ─── customer.subscription.updated / .deleted / invoice.* ───► webhook route → HandleStripeWebhookEvent
```

The Portal owns every post-checkout action (cancel, plan switch, payment method, invoice history). The app has no in-product UI for any of them — it only reads the reconciled state.

## Webhook handling — the side of the system that mutates state

Everything that changes a Subscription after `RegisterAdminAccount` flows through `HandleStripeWebhookEvent` at `src/billing/application/use_cases/handle_stripe_webhook.py`. The route that drives it (`POST /api/v1/billing/webhooks/stripe`) is exempt from JWT and identity middleware — Stripe authenticates via the `Stripe-Signature` header only.

| Stripe event | Effect on the Subscription row |
|---|---|
| `checkout.session.completed` | Find by `stripe_customer_id`, attach `stripe_subscription_id` if not yet set. Does not touch status — the sibling `customer.subscription.created` event carries that. |
| `customer.subscription.created` / `customer.subscription.updated` | Re-derive `plan` from `stripe_price_id` via `PriceCatalog`, map Stripe status to our enum (see below), snapshot `current_period_start/end`, set `type=stripe`. |
| `customer.subscription.deleted` | `status = CANCELLED`. Keeps `plan` so downstream feature-gating can grandfather access until period end if desired. |
| `invoice.payment_failed` | `status = PAST_DUE` (if not already). |
| `invoice.paid` | If status was `PAST_DUE`, flip back to `ACTIVE`. Otherwise no-op (routine renewal invoices don't need to touch state). |
| anything else | Logged, acknowledged, no state change. Stripe retries non-2xx responses, so we always return 200. |

### Stripe status → our status

| Stripe | Ours | Notes |
|---|---|---|
| `active` | `ACTIVE` | |
| `trialing` | `TRIALING` | |
| `past_due` | `PAST_DUE` | |
| `unpaid` | `PAST_DUE` | Dunning failed — same local signal. |
| `canceled` | `CANCELLED` | |
| `incomplete`, `incomplete_expired`, `paused` | `INACTIVE` | Failed initial payment or explicitly paused. Not active, not cancelled. |
| *(unknown)* | `INACTIVE` | Defensive default. |

### Idempotency

Stripe retries webhooks (e.g. if our response takes >10s, or on transient network errors). The first line of `HandleStripeWebhookEvent.execute` is a `try_mark_processed(event_id)` against the `stripe_webhook_events` table (see migration `20260419_030000_o1p2q3r4s5t6_add_stripe_billing.py`). A duplicate `event.id` returns early — no DB mutation, no side effect, 200 ack.

This is the reason the `Subscription` upsert logic is written *as if* it could apply each event multiple times: it can't, but the idempotency guard is the invariant that makes unusual retry scenarios safe.

## HTTP routes

Admin routes live at `src/billing/adapters/api/routes/billing.py`. All three admin routes require OWNER or ADMIN role (enforced via `require_current_org_admin` / `require_org_admin`). The webhook route has no auth dependency — signature verification is done inside the handler.

| Path | Method | Auth | Handler |
|---|---|---|---|
| `/api/v1/admin/billing/subscription` | GET | OWNER/ADMIN | Return the caller's org Subscription — plan, status, period, `stripe_customer_id` (nullable). Used by the frontend subscriptions page on every load. |
| `/api/v1/admin/billing/checkout` | POST | OWNER/ADMIN | `{plan, cadence}` → `{url, session_id}`. Lazily creates the Stripe Customer on first call. |
| `/api/v1/admin/billing/portal` | POST | OWNER/ADMIN | `{}` → `{url}`. 409 if the caller's Subscription has no `stripe_customer_id` yet (i.e. has never upgraded). |
| `/api/v1/billing/webhooks/stripe` | POST | signature header | Verify `Stripe-Signature`, dispatch to `HandleStripeWebhookEvent`. Public path — bypasses JWT and identity middleware. |

## Data model

Persisted at `subscriptions` (migration `20260419_030000_o1p2q3r4s5t6_add_stripe_billing.py` adds `stripe_customer_id` and the `stripe_webhook_events` idempotency table).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `organization_id` | UUID | FK → `organizations.id`, unique (1:1) |
| `plan` | enum | `freemium` / `pro` / `enterprise` |
| `type` | enum | `manual` on seed; `stripe` after first checkout |
| `status` | enum | see mapping above |
| `stripe_customer_id` | text nullable | Set lazily on first `StartCheckoutSession`. Partial unique index where non-null. |
| `stripe_subscription_id` | text nullable | Attached by `checkout.session.completed` webhook |
| `stripe_price_id` | text nullable | Driven by `customer.subscription.*` webhooks |
| `current_period_start` / `current_period_end` | timestamptz nullable | From the Stripe subscription object |
| `created_at`, `updated_at` | timestamptz | |

The `stripe_webhook_events` table is a narrow idempotency log: `(event_id PK, event_type, processed_at)`.

## Acceptance criteria snapshot (see `.claude/specs/active/2026-04-subscriptions-stripe-checkout.md` for the full list)

- Owners and admins can complete a test checkout with card `4242 4242 4242 4242` and land back on `/dashboard/settings/subscriptions?welcome=1`.
- `Subscription` row ends at `TRIALING` + correct `plan` + correct `stripe_*` identifiers — sourced from the webhook, not from the frontend.
- `MEMBER` role cannot call checkout / portal routes (403).
- Webhook with invalid `Stripe-Signature` → 400.
- Replaying the same `event.id` is a DB no-op.

## Dev workflow — replaying events and simulating time

For local dev you run `stripe listen --forward-to http://localhost:8000/api/v1/billing/webhooks/stripe` in a side shell. From there, the Stripe CLI has two escape hatches you'll reach for regularly:

- **Replay a specific event** — `stripe events resend evt_xxx`. Useful when a real event failed in the backend and you want to rerun it against the fixed code. Stripe keeps events 30 days.
- **Fabricate a synthetic event** — `stripe trigger customer.subscription.created`. Exercises signature verification + routing but short-circuits `HandleStripeWebhookEvent._on_subscription_upsert` because the synthetic customer has no matching `stripe_customer_id` in our DB.
- **Simulate time with Stripe Test Clocks** — fast-forward trial→active, renewal cycles, and dunning without waiting real days. Clock must be attached at customer-creation time, so clocks don't apply to subscriptions created by our real app flow (our `StartCheckoutSession` creates clockless customers). Use clocks against CLI-created customers to learn the event sequence; keep real end-to-end verification on the `4242` card flow.

Full runbook with copy-pasteable commands lives in [`README.md § Stripe Billing Setup → Dev helpers`](../../README.md#6-dev-helpers--replay-events-and-simulate-time).

## Related docs

- [`docs/features/organizations.md`](./organizations.md) — the `Subscription` aggregate lives inside the Organizations context.
- [`docs/features/identity.md`](./identity.md) — `require_org_admin` derives admin-ness from membership state at request time.
- Spec: [`.claude/specs/active/2026-04-subscriptions-stripe-checkout.md`](../../.claude/specs/active/2026-04-subscriptions-stripe-checkout.md) (will archive on ship).
