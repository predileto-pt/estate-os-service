# ADR-015: Hybrid owner-publishing model and back-office operations

**Date:** 2026-05-11
**Status:** Proposed (pending — captured for record, not yet scheduled for implementation)

## Context

Today the platform is a B2B product: an agency registers an organization, invites members, and publishes properties under that organization. The `Organization` aggregate has no `type` field — every org is implicitly an agency. Subscriptions, memberships, and property ownership all key on `organization_id`.

Product is considering a pivot to a **hybrid** model:

1. Individual property owners (not agencies) can register on the platform and publish a property themselves.
2. The platform itself acts as the agency-of-record for those owners — handling visits, contracts, and the rental/sale process end-to-end.
3. The commission model for v1 is intentionally crude: an owner pays €1,000 by **bank transfer**; the platform team manually confirms the transfer and flips the property to "allowed to be listed." No Stripe Connect, no automated payouts, no marketplace mechanics in v1.

This pivot raises two distinct architectural questions:

1. **How do individual owners fit into the existing multi-tenant model** that assumes "user → organization → property"?
2. **Where does the platform-side operational workflow live** — confirming manual payments, uploading bank-transfer receipts, gating properties as listable — without polluting the existing tenant-facing admin surface?

A naive answer to (2) is "create a `super_admin` bounded context." That framing conflates a **role** (platform staff with elevated permissions) with a **domain** (the workflows that platform staff actually perform), and would duplicate state that already belongs to `billing` and `properties`. This ADR records the alternative.

## Decision

### 1. Individual owners reuse the `Organization` aggregate

Do **not** introduce a parallel "owner" aggregate. Instead, model an individual owner as a one-member organization, distinguished by an `organization_type` enum on the existing aggregate.

- Add `organization_type` column to `organizations`: enum `AGENCY` | `INDIVIDUAL_OWNER`. Default `AGENCY` for the existing rows (backfill in migration).
- Fork `RegisterAdminAccount` into a second use case `RegisterPropertyOwner` (in the same `organizations` context). Same shape, but creates an org with `organization_type=INDIVIDUAL_OWNER`, a single `Membership` with role `OWNER`, and calls the existing `SeedFreemiumSubscription` port. No changes to identity or billing.
- `require_org_member` and the rest of the auth surface (`src/shared/`) need zero changes: a single-member org is just an org.
- `Property` stays scoped to `organization_id` (FK, non-nullable). The existing `PropertyOwner` value object (document-extracted owner metadata) is unchanged. Publishing logic that validates `property.organization_id == requester.organization_id` already works correctly for both paths.

**Why no new aggregate.** The cross-context contracts (`Membership`, `Subscription`, `Property.organization_id`, listings projection keyed by `organization_id`) all generalize cleanly. A separate "owner" aggregate would force a parallel set of these and double the surface area.

### 2. Listing entitlement is a new billing primitive, not a subscription

The €1,000-to-publish model is not a recurring subscription. Model it as a one-shot `ListingEntitlement` inside the `billing` context, distinct from `Subscription`.

| Field | Notes |
|---|---|
| `id` | UUID, PK |
| `organization_id` | UUID, FK |
| `property_id` | UUID nullable — entitlement may be org-wide or property-scoped (v1: property-scoped) |
| `amount_eur` | numeric(10, 2) — €1,000 in v1 but stored, not hardcoded |
| `paid_at` | timestamptz, set when ops confirms the transfer |
| `expires_at` | timestamptz nullable — listing window |
| `status` | enum: `PENDING` \| `ACTIVE` \| `EXPIRED` \| `VOIDED` |
| `payment_method` | enum: `BANK_TRANSFER` (v1), `STRIPE` (future) |
| `receipt_id` | UUID nullable, FK to `payment_receipts` |
| `confirmed_by_user_id` | UUID nullable, platform staff who confirmed the transfer |
| `created_at`, `updated_at` | timestamptz |

A sibling table `payment_receipts` holds the uploaded bank-transfer receipt artifact (S3 key, content type, uploader, uploaded_at). Receipts are billing artifacts — they belong here, not in a separate context.

Three new use cases in `billing`:

- `RecordManualPayment` — platform staff uploads a receipt and records a `PENDING` entitlement.
- `ConfirmManualPayment` — platform staff flips `PENDING → ACTIVE`, sets `paid_at` and `confirmed_by_user_id`. Emits `LISTING_ENTITLEMENT_GRANTED.v1`.
- `VoidListingEntitlement` — platform staff voids an active or pending entitlement (refund, dispute). Emits `LISTING_ENTITLEMENT_VOIDED.v1`.

### 3. Listing eligibility is a property concern

Whether a property can be published is a state of the property, not of billing. Add a derived gate on `Property`:

- Add `listing_eligible_until: datetime | None` (or a small `ListingEligibility` value object if richer state is needed later).
- `PublishProperty` already validates aggregate state; extend it to require `listing_eligible_until is not None and listing_eligible_until > now()` **only when** `organization.organization_type == INDIVIDUAL_OWNER`. Agencies keep their current subscription-gated flow.
- `properties` listens for `LISTING_ENTITLEMENT_GRANTED.v1` / `LISTING_ENTITLEMENT_VOIDED.v1` and updates `listing_eligible_until` accordingly. Standard cross-context event consumption — no direct imports.

**Why not put the gate on `billing`.** Asking "can I publish this property?" should be answerable from the property aggregate alone. Forcing every read of "is publishable" through a billing port would tangle the publishing hot path with billing availability.

### 4. No `super_admin` bounded context. Platform-staff is a role.

Platform staff (the user) act outside the multi-tenant boundary — they need to confirm payments and void entitlements across any org, without being a member of those orgs. This is an **authorization** concern, not a domain.

- Add a `PlatformRole` table (or a `platform_staff` boolean on `User`, depending on whether multiple platform roles are ever expected; v1: boolean is enough).
- Add `require_platform_staff` dependency in `src/shared/`, mirroring `require_org_member`. Routes for the back-office dashboard depend on this instead of `require_org_member`.
- Platform staff identity is still a `User` — same auth, same identity middleware, same Supabase session. The dependency just checks a different flag.

### 5. A small `back_office` context — only for what doesn't fit elsewhere

The workflows themselves (confirm payment, void entitlement, gate listing) live in their domain contexts (`billing`, `properties`). What *doesn't* fit anywhere is the **cross-cutting audit log**: a single chronological feed of "platform staff X did action Y on entity Z at time T." Spreading audit rows across each context's tables would make the inevitable "what did ops do this week" question expensive to answer.

Introduce `back_office/` as a thin bounded context with one aggregate: `OperationsLog`. Append-only. Subscribes to the billing/properties events that platform staff trigger and records them with the staff actor. No business logic of its own.

| Field | Notes |
|---|---|
| `id` | UUID, PK |
| `actor_user_id` | UUID, platform staff who triggered the action |
| `action` | text — `MANUAL_PAYMENT_RECORDED`, `MANUAL_PAYMENT_CONFIRMED`, `LISTING_ENTITLEMENT_VOIDED`, ... |
| `target_kind` | text — `ORGANIZATION`, `PROPERTY`, `LISTING_ENTITLEMENT`, `RECEIPT` |
| `target_id` | UUID |
| `payload` | jsonb — snapshot of relevant fields at the time of the action |
| `created_at` | timestamptz |

The context exposes one route (`GET /api/v1/back-office/operations-log`) and one use case (`ListOperations`, paginated + filterable). It owns no business logic — it's a read-optimized projection of platform-staff activity. Cross-context dependency: subscribes to billing/properties events via the existing event bus (ADR-007, ADR-008), no direct imports.

**Why this is a context, not a row in each domain table.** If audit rows lived in `billing.audit_log` and `properties.audit_log`, "what did ops do this week" would require querying N tables and union-ing. An append-only feed is cheap to maintain (one event subscriber per relevant event), trivial to query, and naturally extensible — when bookings/contracts join the platform-staff surface, they just emit events.

### 6. New frontend app: `back-office/`

The back-office dashboard is a separate Next.js app, sibling to `agencies-dashboard/`. It hits the same `estate-os-service` backend, but every route is gated by `require_platform_staff`. The audience, auth model, and UI are different enough that bolting it onto `agencies-dashboard` would force role-based branching throughout the existing app.

- Same monorepo conventions as the other Next.js apps (App Router, locale-based routing, Tailwind v4, Zod, custom dictionary i18n).
- New frontend routes (out of scope for this ADR — covered when the frontend spec lands).

## Consequences

- **One enum column** on `organizations` (`organization_type`). Migration is a column add + backfill of existing rows to `AGENCY`.
- **One new use case** in `organizations` (`RegisterPropertyOwner`). Reuses every existing port (identity registration, freemium seeding).
- **Two new tables** in `billing`: `listing_entitlements`, `payment_receipts`. Two new events: `LISTING_ENTITLEMENT_GRANTED.v1`, `LISTING_ENTITLEMENT_VOIDED.v1`.
- **One column** on `properties.property`: `listing_eligible_until`. One new event subscription in `properties` for the two listing-entitlement events.
- **One new authorization primitive**: `platform_staff` flag on `User` (or `PlatformRole` table) and `require_platform_staff` dependency.
- **One new thin bounded context**: `back_office/` with a single `OperationsLog` aggregate, subscribing to billing/properties events.
- **One new S3 prefix or bucket** for payment receipts. Same considerations as ADR-011's media bucket (separate blast radius, separate lifecycle).
- **One new frontend app**: `back-office/`, sibling to `agencies-dashboard/`. Not covered by this ADR.
- **Agency flow is unchanged.** Every existing route, use case, repository, and projection continues to work. The hybrid path adds a parallel registration entry point and a publishing gate that only triggers for `INDIVIDUAL_OWNER` orgs.
- **Listings projection requires no change.** It already keys on `organization_id` and consumes `PROPERTY_*.v1` events — it doesn't care whether the org is an agency or an individual.
- **No payout / Connect machinery.** The €1,000 flows to the platform's bank account and stays there. The owner gets the listing window; the platform handles visits/contracts and (when sale/rental closes) pays the owner out-of-band. Automated payouts are explicitly deferred.

## Alternatives considered

1. **New `OwnerProperty` aggregate parallel to `Property`.** Rejected: doubles the surface area of every read path (listings projection, search, bookings, contracts). The existing `Organization`-scoped model generalizes cleanly with one enum column.
2. **Add `owner_user_id` FK to `Property` and make `organization_id` nullable.** Rejected: every existing query, RLS policy, and event subscriber assumes `organization_id` is present. Making it nullable is a load-bearing change with no payoff — a one-member org satisfies the same use case at zero cost.
3. **Model the €1,000 as a one-shot `MANUAL` `Subscription`.** Tempting because `Subscription.type=MANUAL` already exists. Rejected: subscriptions are recurring by design (period start/end, renewal, status transitions). Forcing a one-shot payment through that aggregate would muddy what "subscription status" means and complicate the agency-side flow that genuinely is recurring. `ListingEntitlement` keeps the two concepts separate.
4. **`super_admin` bounded context owning payments, entitlements, and property gating.** Rejected: this is the framing the user originally proposed. It conflates role with domain and would force `super_admin` to own state (`Subscription`, `Property.listing_eligible_until`) that already belongs to other contexts. The contexts would end up double-writing or the `super_admin` context would proxy every read — neither is good.
5. **Store the audit log inside each domain context (`billing.audit_log`, `properties.audit_log`).** Rejected: makes the "what did ops do this week" query span N tables. An append-only platform-wide log is cheaper to write and cheaper to read.
6. **Skip the audit log in v1.** Tempting given how small the platform-staff team is. Rejected: ops actions touch money. The first time something looks wrong, "who confirmed which payment when" is the question that has to be answerable in seconds. Adding it later means losing the history of the period when we needed it most.
7. **Bolt the back-office UI onto `agencies-dashboard`.** Rejected: different audience (internal staff vs. paying customers), different auth model (`platform_staff` flag vs. org membership), and different UI priorities (operational density vs. brand polish). Branching every page on role is a recipe for accidents.
8. **Use Stripe (or another PSP) for the €1,000 from day one.** Out of scope for v1; the bank-transfer + manual-confirmation flow is explicitly the product's chosen starting point. The `payment_method` enum on `ListingEntitlement` leaves the door open for `STRIPE` later without a schema change.

## Out of scope

- **Frontend spec for the `back-office/` app.** Captured here only as "it exists and is separate"; the actual routes, components, and i18n shape are a separate spec.
- **Stripe / automated payments / Stripe Connect.** v1 is bank transfer + manual confirmation.
- **Owner payouts.** Out-of-band in v1 — the platform pays owners outside the system after a deal closes.
- **AMI license and other Portuguese real-estate-mediation regulatory compliance.** This is a legal/operational prerequisite for acting as agency-of-record; it is not a software concern and lives outside this repo.
- **Mandate / representation contracts** between the platform and individual owners. May fit into `contract_intelligence` later; explicitly deferred.
- **Booking and contract flows when the platform itself is the agency.** The existing `bookings` and `contract_intelligence` contexts already model these for agencies; the changes needed to support "platform staff as the visiting party / counterparty" are a follow-up ADR.
- **Per-property vs. org-wide entitlements.** v1 is property-scoped (one entitlement unlocks one property). An "all properties this org publishes for the next 12 months" variant is a follow-up.
- **Refund / dispute UX.** `VoidListingEntitlement` exists; the operational workflow around when and how to use it is a runbook, not a domain decision.
- **Notifications** to the owner when their payment is confirmed and the listing goes live. Handled by the existing notifications surface; out of scope here.

## Iteration plan

This ADR captures the architecture at a level sufficient to commit to the **shape** of the pivot — it is **not** an implementation spec. We iterate by adding:

- v2: concrete domain models for `ListingEntitlement`, `PaymentReceipt`, `OperationsLog`, including exception hierarchy and event payload schemas.
- v3: schema migrations (DDL), event subscriber wiring, and idempotency requirements for the `LISTING_ENTITLEMENT_*` events.
- v4: `RegisterPropertyOwner` use case detail (input validation, organization defaults, conflicts with existing users).
- v5: back-office UI spec — routes, role surface, i18n.
- v6: platform-as-agency workflows for bookings and contracts (likely a separate ADR — flagged here only as the next domino).

Each iteration appends a section here and bumps the status. Status flips from **Proposed (pending)** to **Accepted** when product confirms the pivot is going ahead, at which point the v2+ sections move into implementation specs under `.claude/specs/active/`.
