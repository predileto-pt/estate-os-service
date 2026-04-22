#!/usr/bin/env bash
# Stripe Test Clock helpers for local dev.
#
# Test mode only. Clocks let you fast-forward a simulated clock so billing
# events (trial→active, renewals, dunning) fire on demand without waiting
# real days. See README § 6 "Dev helpers" for the full walkthrough.
#
# Usage:
#   scripts/stripe-clock.sh setup <email> <price_id> [trial_days]
#   scripts/stripe-clock.sh status <clock_id>
#   scripts/stripe-clock.sh advance <clock_id> <when>    # +7d | +12h | +30m | <unix_ts>
#   scripts/stripe-clock.sh end-trial <clock_id>          # jump to sub.trial_end + 60s
#   scripts/stripe-clock.sh renew <clock_id>              # jump one billing cycle (+30d)
#   scripts/stripe-clock.sh list
#   scripts/stripe-clock.sh cleanup <clock_id>
#   scripts/stripe-clock.sh hijack <stripe_sub_id> <admin_email>
#   scripts/stripe-clock.sh hijack-rollback <admin_email>
#
# Every subcommand that mutates state polls the clock until it's back to
# `ready` and prints the events that fired during the advance window.
#
# `hijack` / `hijack-rollback` need `DATABASE_URL` exported (load your
# backend .env first: `set -a; source .env; set +a`) and the `psql` binary
# on PATH. See "Swap stripe_customer_id" in README § 6.

set -euo pipefail

require_stripe_cli() {
  if ! command -v stripe &>/dev/null; then
    echo "stripe CLI not found. Install from https://stripe.com/docs/stripe-cli" >&2
    exit 1
  fi
}

require_psql() {
  if ! command -v psql &>/dev/null; then
    echo "psql not found. Install postgresql client tools." >&2
    exit 1
  fi
  if [ -z "${DATABASE_URL:-}" ]; then
    echo "DATABASE_URL not set. Load your backend .env first:" >&2
    echo "  set -a; source .env; set +a" >&2
    exit 1
  fi
}

# Strip SQLAlchemy-style `+asyncpg` dialect marker so psql accepts the URL.
psql_url() {
  echo "${DATABASE_URL/postgresql+asyncpg/postgresql}"
}

usage() {
  grep -E '^#' "$0" | sed 's/^# \?//'
  exit 1
}

# Parse a `+Nd|+Nh|+Nm|+Ns` relative offset or a raw Unix timestamp.
# Prints the resolved absolute Unix timestamp.
resolve_when() {
  local now="$1" when="$2"
  case "$when" in
    +*d) echo $((now + ${when#+} * 86400)) ;;
    +*h) echo $((now + ${when#+} * 3600)) ;;
    +*m) echo $((now + ${when#+} * 60)) ;;
    +*s) echo $((now + ${when#+})) ;;
    *[!0-9]*) echo "Invalid time: $when (use +7d / +12h / +30m / +60s / unix_ts)" >&2; exit 1 ;;
    *) echo "$when" ;;
  esac
}

json_field() {
  # Extract a top-level string or numeric field from a Stripe JSON blob.
  #   json_field <json> <field>
  local json="$1" field="$2"
  echo "$json" | grep -E "^  \"$field\":" | head -1 | sed -E "s/^  \"$field\": ?\"?([^\",]*)\"?,?$/\1/"
}

clock_status() {
  local clock_id="$1"
  stripe test_helpers test_clocks retrieve "$clock_id" 2>&1 \
    | grep '"status"' | head -1 | awk -F'"' '{print $4}'
}

clock_frozen_time() {
  local clock_id="$1"
  stripe test_helpers test_clocks retrieve "$clock_id" 2>&1 \
    | grep '"frozen_time"' | head -1 | awk '{print $2}' | tr -d ','
}

poll_clock() {
  # Block until clock is `ready` or `internal_failure`. Times out at ~2min.
  local clock_id="$1" i=0 max=40 s
  while [ $i -lt $max ]; do
    s=$(clock_status "$clock_id")
    if [ "$s" = "ready" ] || [ "$s" = "internal_failure" ]; then
      echo "  clock status: $s"
      [ "$s" = "internal_failure" ] && exit 1
      return 0
    fi
    sleep 3
    i=$((i + 1))
  done
  echo "  timed out waiting for clock to settle (status=$s)" >&2
  exit 1
}

print_recent_events() {
  # Print event types fired in the last N seconds. Best-effort — Stripe's
  # list endpoint returns in reverse chrono, so we grab the top few.
  echo "  recent events (top 8):"
  stripe events list --limit 8 2>&1 \
    | grep '"type"' | grep -vE 'flexible|self|recurring|subscription_item_details|price_details|subscription_details' \
    | head -8 | sed 's/^/  /'
}

cmd_setup() {
  local email="${1:-}" price_id="${2:-}" trial_days="${3:-7}"
  [ -z "$email" ] || [ -z "$price_id" ] && { echo "usage: setup <email> <price_id> [trial_days]" >&2; exit 1; }

  echo "Creating clock frozen at now..."
  local clock_json clock_id
  clock_json=$(stripe test_helpers test_clocks create \
    --frozen-time "$(date +%s)" \
    --name "dev-$(date +%Y%m%d-%H%M%S)")
  clock_id=$(json_field "$clock_json" id)
  echo "  clock: $clock_id"

  echo "Creating customer attached to clock..."
  local customer_json customer_id
  customer_json=$(stripe customers create --email="$email" --test-clock="$clock_id")
  customer_id=$(json_field "$customer_json" id)
  echo "  customer: $customer_id"

  echo "Attaching test card (pm_card_visa)..."
  stripe payment_methods attach pm_card_visa --customer="$customer_id" >/dev/null
  stripe customers update "$customer_id" \
    -d "invoice_settings[default_payment_method]=pm_card_visa" >/dev/null

  echo "Creating subscription with $trial_days-day trial..."
  local sub_json sub_id
  sub_json=$(stripe subscriptions create \
    --customer="$customer_id" \
    -d "items[0][price]=$price_id" \
    --trial-period-days="$trial_days")
  sub_id=$(json_field "$sub_json" id)
  echo "  subscription: $sub_id"

  echo ""
  echo "Setup complete."
  echo "  Clock:        $clock_id"
  echo "  Customer:     $customer_id"
  echo "  Subscription: $sub_id"
  echo ""
  echo "Next: scripts/stripe-clock.sh end-trial $clock_id"
}

cmd_status() {
  local clock_id="${1:-}"
  [ -z "$clock_id" ] && { echo "usage: status <clock_id>" >&2; exit 1; }

  echo "=== clock ==="
  stripe test_helpers test_clocks retrieve "$clock_id" 2>&1 \
    | grep -E '"(id|name|status|frozen_time)"'

  echo ""
  echo "=== attached customers + subscriptions ==="
  # Clocks don't expose an inverse "list customers on this clock" API,
  # so find customers via subscriptions.list + filter. Limit to 5.
  local subs
  subs=$(stripe subscriptions list --limit 20 --expand 'data.customer' 2>&1)
  echo "$subs" | grep -E '"(id|status|test_clock)"|"current_period_start"|"current_period_end"' \
    | head -20
}

cmd_advance() {
  local clock_id="${1:-}" when="${2:-}"
  [ -z "$clock_id" ] || [ -z "$when" ] && { echo "usage: advance <clock_id> <when>" >&2; exit 1; }

  local now target
  now=$(clock_frozen_time "$clock_id")
  target=$(resolve_when "$now" "$when")

  if [ "$target" -le "$now" ]; then
    echo "Target time ($target) is not after current frozen time ($now). Clocks only advance forward." >&2
    exit 1
  fi

  local delta_s=$((target - now))
  echo "Advancing clock $clock_id"
  echo "  from: $now ($(date -r "$now" 2>/dev/null || echo ?))"
  echo "  to:   $target ($(date -r "$target" 2>/dev/null || echo ?))"
  echo "  delta: ${delta_s}s"

  stripe test_helpers test_clocks advance "$clock_id" --frozen-time "$target" >/dev/null
  poll_clock "$clock_id"
  print_recent_events
}

cmd_end_trial() {
  local clock_id="${1:-}"
  [ -z "$clock_id" ] && { echo "usage: end-trial <clock_id>" >&2; exit 1; }

  # Find a subscription attached to this clock's customer, with trial_end set.
  local trial_end
  trial_end=$(stripe subscriptions list --limit 20 2>&1 \
    | grep -E '"(test_clock|trial_end)"' \
    | awk -v c="$clock_id" '
        /"test_clock"/ { clk = $2; gsub(/[",]/, "", clk) }
        /"trial_end"/ { te = $2; gsub(/,/, "", te) }
        clk == c && te != "" && te != "null" { print te; exit }')

  if [ -z "$trial_end" ] || [ "$trial_end" = "null" ]; then
    echo "Couldn't find a trialing subscription on this clock. Run \`status $clock_id\` to inspect." >&2
    exit 1
  fi

  echo "Found trial_end=$trial_end. Advancing to trial_end + 60s..."
  cmd_advance "$clock_id" $((trial_end + 60))
}

cmd_renew() {
  # Advance one billing cycle. Defaults to 30 days; pass a second arg for days.
  local clock_id="${1:-}" days="${2:-30}"
  [ -z "$clock_id" ] && { echo "usage: renew <clock_id> [days]" >&2; exit 1; }
  cmd_advance "$clock_id" "+${days}d"
}

cmd_list() {
  echo "=== test clocks ==="
  stripe test_helpers test_clocks list --limit 20 2>&1 \
    | grep -E '"(id|name|status|frozen_time)"'
}

cmd_cleanup() {
  local clock_id="${1:-}"
  [ -z "$clock_id" ] && { echo "usage: cleanup <clock_id>" >&2; exit 1; }

  echo "Deleting clock $clock_id..."
  echo "(this also deletes attached customers + their subscriptions)"
  stripe test_helpers test_clocks delete "$clock_id" 2>&1 | grep -E '"(id|deleted)"'
}

cmd_hijack() {
  # hijack <stripe_sub_id> <admin_email>
  # Points the admin's local subscription row at a clock-attached Stripe
  # customer/subscription, so webhook events from the clock land on a real
  # backend-owned row and run through HandleStripeWebhookEvent normally.
  local sub_id="${1:-}" admin_email="${2:-}"
  [ -z "$sub_id" ] || [ -z "$admin_email" ] && {
    echo "usage: hijack <stripe_sub_id> <admin_email>" >&2
    exit 1
  }
  require_psql

  echo "Retrieving Stripe subscription $sub_id..."
  local sub_json customer_id
  sub_json=$(stripe subscriptions retrieve "$sub_id")
  customer_id=$(echo "$sub_json" | grep '"customer":' | head -1 | awk -F'"' '{print $4}')
  if [ -z "$customer_id" ]; then
    echo "Couldn't parse customer id from: $sub_id" >&2
    exit 1
  fi
  echo "  stripe_customer_id: $customer_id"

  echo "Patching local subscriptions row for admin $admin_email..."
  local result
  result=$(psql "$(psql_url)" -X -A -q --tuples-only \
    -v stripe_customer_id="$customer_id" \
    -v stripe_subscription_id="$sub_id" \
    -v admin_email="$admin_email" <<'SQL'
UPDATE subscriptions s
SET stripe_customer_id    = :'stripe_customer_id',
    stripe_subscription_id = :'stripe_subscription_id',
    status                = 'trialing',
    plan                  = 'pro',
    type                  = 'stripe',
    updated_at            = NOW()
FROM memberships m, users u
WHERE s.organization_id = m.organization_id
  AND m.user_id = u.id
  AND u.email = :'admin_email'
RETURNING s.organization_id, s.plan, s.status, s.stripe_customer_id, s.stripe_subscription_id;
SQL
  )

  if [ -z "$result" ]; then
    echo "  no subscription found for admin '$admin_email'." >&2
    echo "  Has this user registered through the app? Check:" >&2
    echo "    psql \"\$(echo \$DATABASE_URL | sed 's/+asyncpg//')\" -c \"SELECT u.email FROM users u JOIN memberships m ON m.user_id = u.id;\"" >&2
    exit 1
  fi

  echo "  patched: $result"
  echo ""
  echo "Hijack complete. Clock events will now land on this admin's row."
  echo "To restore:"
  echo "  scripts/stripe-clock.sh hijack-rollback $admin_email"
}

cmd_hijack_rollback() {
  local admin_email="${1:-}"
  [ -z "$admin_email" ] && { echo "usage: hijack-rollback <admin_email>" >&2; exit 1; }
  require_psql

  echo "Restoring $admin_email's subscription to freemium defaults..."
  local result
  result=$(psql "$(psql_url)" -X -A -q --tuples-only \
    -v admin_email="$admin_email" <<'SQL'
UPDATE subscriptions s
SET stripe_customer_id     = NULL,
    stripe_subscription_id  = NULL,
    stripe_price_id        = NULL,
    status                 = 'active',
    plan                   = 'freemium',
    type                   = 'manual',
    current_period_start   = NOW(),
    current_period_end     = NULL,
    updated_at             = NOW()
FROM memberships m, users u
WHERE s.organization_id = m.organization_id
  AND m.user_id = u.id
  AND u.email = :'admin_email'
RETURNING s.organization_id, s.plan, s.status;
SQL
  )

  if [ -z "$result" ]; then
    echo "  no subscription found for admin '$admin_email'. Nothing to roll back." >&2
    exit 1
  fi

  echo "  restored: $result"
  echo ""
  echo "Rollback complete. Stripe-side clock + customer are untouched."
  echo "Run \`scripts/stripe-clock.sh cleanup <clock_id>\` to delete them."
}

require_stripe_cli

sub="${1:-}"
shift || true

case "$sub" in
  setup)            cmd_setup "$@" ;;
  status)           cmd_status "$@" ;;
  advance)          cmd_advance "$@" ;;
  end-trial)        cmd_end_trial "$@" ;;
  renew)            cmd_renew "$@" ;;
  list)             cmd_list ;;
  cleanup)          cmd_cleanup "$@" ;;
  hijack)           cmd_hijack "$@" ;;
  hijack-rollback)  cmd_hijack_rollback "$@" ;;
  ""|-h|--help|help) usage ;;
  *) echo "Unknown subcommand: $sub" >&2; usage ;;
esac
