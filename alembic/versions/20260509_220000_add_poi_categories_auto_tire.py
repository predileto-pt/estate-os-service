"""extend poi_category enum with tire_shop and auto_shop

Revision ID: 4f1c8b2d9e30
Revises: e6eb6e539aea
Create Date: 2026-05-09 22:00:00.000000

Adds two new POI categories surfaced municipality-wide for PT
listings. Both ride on Google's `car_repair` place_type and are
disambiguated at discovery time via per-category keywords ("pneus" /
"oficina mecânica"). Postgres enum extension is one-way at the type
level (`ALTER TYPE ... ADD VALUE` cannot be rolled back inside a
transaction), so the downgrade is a no-op — rolling these out is
forward-only.
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "4f1c8b2d9e30"
down_revision: Union[str, Sequence[str], None] = "e6eb6e539aea"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `ALTER TYPE ADD VALUE` cannot run inside a transaction block on
    # older Postgres versions; modern Supabase (PG 15+) accepts it.
    # `IF NOT EXISTS` keeps the migration idempotent on partial reruns.
    op.execute("ALTER TYPE poi_category ADD VALUE IF NOT EXISTS 'tire_shop'")
    op.execute("ALTER TYPE poi_category ADD VALUE IF NOT EXISTS 'auto_shop'")


def downgrade() -> None:
    # Postgres has no `ALTER TYPE DROP VALUE`. Removing an enum value
    # would require recreating the type and rewriting every dependent
    # column. This migration is forward-only.
    pass
