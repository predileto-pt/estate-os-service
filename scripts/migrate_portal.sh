#!/bin/bash
# Run Alembic migrations against the portal DB (PORTAL_DATABASE_URL),
# using the portal-scoped Alembic config (alembic-portal.ini).
#
# Usage:
#   bash scripts/migrate_portal.sh upgrade head
#   bash scripts/migrate_portal.sh revision --autogenerate -m "add bar to sessions"
#   bash scripts/migrate_portal.sh downgrade -1
#
# Spec: 2026-05-portal-session-backend §2.

set -euo pipefail

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [[ -z "${PORTAL_DATABASE_URL:-}" ]]; then
  echo "ERROR: PORTAL_DATABASE_URL is empty. Cannot run portal migrations." >&2
  echo "Set PORTAL_DATABASE_URL in your environment or .env file." >&2
  exit 2
fi

# Print target host:port (mask credentials).
TARGET=$(echo "$PORTAL_DATABASE_URL" | sed -E 's#^[a-z+]+://[^@]+@##; s#/.*$##')
echo "→ portal migrations: target=${TARGET}" >&2

exec uv run alembic -c alembic-portal.ini "$@"
