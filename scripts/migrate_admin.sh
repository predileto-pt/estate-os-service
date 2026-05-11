#!/bin/bash
# Run Alembic migrations against the admin DB (DATABASE_URL).
#
# Usage:
#   bash scripts/migrate_admin.sh upgrade head
#   bash scripts/migrate_admin.sh revision --autogenerate -m "add foo"
#
# Spec: 2026-05-portal-session-backend §2.

set -euo pipefail

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "ERROR: DATABASE_URL is empty. Cannot run admin migrations." >&2
  echo "Set DATABASE_URL in your environment or .env file." >&2
  exit 2
fi

# Print target host:port (mask credentials). Strip scheme + userinfo.
TARGET=$(echo "$DATABASE_URL" | sed -E 's#^[a-z+]+://[^@]+@##; s#/.*$##')
echo "→ admin migrations: target=${TARGET}" >&2

exec uv run alembic "$@"
