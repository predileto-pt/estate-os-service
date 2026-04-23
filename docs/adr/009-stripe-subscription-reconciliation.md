# ADR-009: Manual Stripe subscription reconciliation

**Date:** 2026-04-23
**Status:** Proposed

## Context

Webhooks (`customer.subscription.*`, `invoice.*`, `checkout.session.completed`) are the only mechanism keeping the local `subscriptions` table in sync with Stripe. The webhook pipeline drifts for predictable reasons:

- **Dropped deliveries.** Stripe retries `customer.subscription.updated` with exponential backoff and gives up after ~3 days. A transient DB error we failed to retry leaves the row stale forever.
- **Signature rotation windows.** During secret rotation, events with the old signing secret get rejected. If the rotation straddles a subscription change, we miss the event.
- **Live-vs-test-mode mix-ups.** Observed firsthand this session — a developer was testing in live mode while the backend was keyed for test mode. Every webhook landed on the 400 path. Nobody noticed for days because the subscription was a developer test, not a real user.
- **Service downtime.** If the webhook endpoint is down past Stripe's retry window, those events are gone.
- **Mid-processing failures we swallowed.** The handler logs and returns 200 on some code paths to avoid Stripe re-sending forever. Good for handler hygiene, bad for data integrity.

We have no detection or repair path today. The only remediation is for an engineer to notice a wrong plan or status, open the Stripe dashboard, and manually replay the event. That requires (a) noticing, and (b) remembering which event. Both fail silently.

Two recent pieces of session work raised the stakes enough to act:

1. We persist the full raw webhook payload now (`stripe_webhook_events` table, commit `cf1091222591` and predecessors). Replay from our own DB is technically possible, but we still don't *notice* drift.
2. We're rolling out `/upgrade` + Customer Portal to real paying customers. A silently-stuck subscription is a billing correctness bug with direct revenue impact, visible to the user the next time they hit the portal and see a plan that doesn't match what they're paying for.

We want a mechanism that (a) pulls canonical subscription state from Stripe, (b) compares it against the local row, and (c) overwrites the local row when they differ — treating Stripe as the source of truth. It should avoid racing in-flight webhooks and should be cheap to run and cheap to not run.

## Decision

### 1. New use case `ReconcileStripeSubscriptions`

Located at `src/billing/application/use_cases/reconcile_stripe_subscriptions.py`. Its responsibilities:

- List eligible local subscriptions (filter below)
- For each: call the Stripe gateway to retrieve canonical state
- Apply that state to the local row via a **shared helper** (see §4), only persisting if anything changed
- Return a `ReconcileReport` dataclass with counts: `scanned`, `in_sync`, `drift_fixed`, `cancelled_on_stripe`, `errors`

One failure does not poison the batch — each subscription is a try/except boundary. Errors are counted and logged, and the loop continues.

### 2. Eligibility filter — the cooldown rule

New repository method `list_stripe_subs_updated_before(cutoff: datetime) -> list[Subscription]` with filter:

```sql
WHERE type = 'stripe'
  AND stripe_subscription_id IS NOT NULL
  AND status != 'cancelled'
  AND updated_at < :cutoff
```

Reasoning:

- `type = 'stripe'` — freemium/manual subscriptions have no Stripe counterpart to reconcile against.
- `stripe_subscription_id IS NOT NULL` — pre-checkout placeholders (customer created, no subscription yet) have nothing to fetch.
- `status != 'cancelled'` — terminal status. Don't burn Stripe API calls re-fetching rows that will never legitimately change.
- `updated_at < cutoff` (default `NOW() - 1 hour`) — **this is the key rule.** It prevents us from racing in-flight webhooks: if a webhook just landed and the row is fresh, we leave it alone. And because every write to this table IS a Stripe sync (there are no unrelated writes), "recently updated" is equivalent to "Stripe pipeline is working for this sub right now — no reconciliation needed."

The column `updated_at` is reused, not replaced. A `last_reconciled_at` column was considered and rejected (see Alternatives).

### 3. Stripe gateway addition

Add `retrieve_subscription(subscription_id: str) -> dict` to `BillingGateway`:

```python
async def retrieve_subscription(self, *, subscription_id: str) -> dict:
    def _retrieve() -> dict:
        try:
            sub = stripe.Subscription.retrieve(subscription_id)
        except stripe.InvalidRequestError as exc:
            if getattr(exc, "code", None) == "resource_missing":
                raise StripeSubscriptionNotFound(subscription_id) from exc
            raise
        return sub.to_dict(for_json=True)  # Decimal → str, per this session's fix
    return await asyncio.to_thread(_retrieve)
```

New domain exception `StripeSubscriptionNotFound` in the billing exceptions module. When the reconcile loop catches it, the local row is flipped to `CANCELLED` — Stripe deleted the subscription out from under us and we follow.

The `InMemoryBillingGateway` gains a `preset_subscriptions: dict[str, dict]` field and a `retrieve_subscription` method that reads from it (raising `StripeSubscriptionNotFound` on miss) so tests can seed "what Stripe would return."

### 4. Shared state-mapper helper — the most important structural move

Extract the body of `HandleStripeWebhookEvent._on_subscription_upsert` into a module-level function:

```python
def apply_stripe_subscription_state(
    sub: Subscription,
    data: dict,
    price_catalog: PriceCatalog,
) -> bool:
    """Mutate `sub` to match Stripe's canonical `data`. Returns True if any
    field changed — caller decides whether to persist."""
```

The existing webhook handler shrinks to: resolve the sub by customer id, call the helper, persist if it returned True. The reconcile use case does the same: list subs, call the helper for each, persist if True.

**Why this matters:** one implementation means webhooks and reconciliation produce bit-identical results from bit-identical Stripe payloads. Any future change to the mapping (new status, new field, new plan) happens in exactly one place. Without this extraction, the reconciler would be a second implementation of the same logic — a drift source of its own.

The helper encapsulates the Clover-API fallback (top-level `current_period_{start,end}` → items[0] fallback) and the unknown-price-id handling that already live in the webhook handler.

### 5. Drift logging as a passive quality signal

Every drift fix emits:

```python
log.info(
    "reconcile.drift_fixed",
    organization_id=str(sub.organization_id),
    stripe_subscription_id=sub.stripe_subscription_id,
    plan=sub.plan.value,
    status=sub.status.value,
)
```

This is not just an audit trail — it's the hook point for future alerting. If `reconcile.drift_fixed` fires on the same `stripe_subscription_id` twice in a week, something in the webhook pipeline is broken for that specific sub. Over time, the *rate* of drift fixes is a proxy for webhook pipeline health.

Missing-on-Stripe events get their own log key (`reconcile.subscription_missing_on_stripe`). Per-subscription exceptions go through `log.exception("reconcile.retrieve_failed", ...)`.

### 6. Manual trigger

CLI entrypoint at `src/billing/entrypoints/reconcile_stripe_subscriptions.py`:

```bash
uv run python -m billing.entrypoints.reconcile_stripe_subscriptions \
    [--cooldown-hours N]   # default 1
    [--dry-run]            # log everything, write nothing
```

Same pattern as `src/listings/entrypoints/backfill_property_listings.py`. Reads bootstrap, pulls `reconcile_stripe_subscriptions` from the billing container, runs it, prints the report.

No cron, no Lambda, no EventBridge. An operator (or, post-deploy, a `render.yaml` cron job / GitHub Actions schedule / whichever scheduler the deploy env already has) invokes it on demand. Once we have evidence the use case is correct, automation is a one-line change: a Lambda handler that calls `container.reconcile_stripe_subscriptions.execute()`.

## Consequences

**Positive**

- Self-healing for webhook drift after operator invocation.
- Webhook handler and reconciler share one mapping implementation — eliminates a class of "two places that map Stripe → local" bugs.
- Drift counts become a passive health signal for the webhook pipeline itself.
- Trivial upgrade path to scheduled execution: the use case is container-wired; a Lambda handler is ~10 lines.
- Dry-run mode exists from day one, so the first production use can be a no-op report.

**Negative / trade-offs**

- Drift persists until the operator runs the CLI. Acceptable at single-digit paying orgs; likely unacceptable past ~100 orgs (revisit with scheduling then).
- Stripe API reads scale with subscription count. Prod limit is 100 reads/sec; at 10k subs that's ~100s per run. Not a short-term concern.
- `resource_missing` → `CANCELLED` is correct for current Stripe behavior but couples the reconciler to that specific error code. Worth re-checking if we ever see `resource_missing` returned for transient reasons.
- The 1-hour cooldown means a drift repaired in a webhook burst gets re-examined an hour later. That's the point, and it's cheap.

## Alternatives considered

- **EventBridge → Lambda automated schedule.** On-brand with ADR-002 and the eventual destination. Deferred because manual CLI validates the use case before we commit to the infra, and because at current scale the operator knowing to run it is acceptable. Flip to automated when (a) paying org count grows, or (b) we see drift frequently enough that manual feels slow.
- **Separate `last_reconciled_at` column.** Rejected. Adds DDL and creates a column whose meaning duplicates `updated_at` in this specific table. In the `subscriptions` table, every write IS a Stripe sync — there's no concept of "updated for some other reason but not yet reconciled." Reusing `updated_at` is lossless here.
- **No cooldown — reconcile everything every run.** Rejected. Stripe's API is eventually consistent with its own webhook delivery; a fresh read seconds after a webhook can return stale data. Without the cooldown we'd occasionally clobber correct local state with older Stripe state.
- **Reverse reconciliation (find Stripe subscriptions with no local row).** Deferred. Different problem — this is audit, not repair. Our immediate pain is "local is wrong," not "Stripe has orphans."
- **In-process APScheduler background loop in the FastAPI app.** Rejected. Would duplicate work on multi-instance deploys, die with the process, and conflict with the Lambda-ward direction of ADR-002.

## Out of scope

- Automated scheduling (cron, Lambda, EventBridge) — explicit follow-up once this use case is validated against production.
- Alerting on drift (Slack / PagerDuty) — the structured log is the future hook point.
- Reverse reconciliation (Stripe → local orphan detection).
- UI surface for drift events in the agencies dashboard.
- Reconciliation of non-subscription Stripe state (customers, invoices, prices).
