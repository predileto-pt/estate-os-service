"""Add `title` to properties + property_listings (required, with backfill)

Revision ID: a8c4f3d2e7b5
Revises: c2c206f0a679
Create Date: 2026-05-11 14:00:00.000000

User-facing title that the admin sets at property registration time.
Carried through the domain-event payload so the listings projector
materializes it onto `property_listings.title` on every subsequent
upsert.

Both columns land as NOT NULL. To keep the migration green against
the existing dev data, the migration:

1. Adds `title` as nullable on both tables.
2. Backfills existing rows with `"<typology> · <address>"` for
   `properties`, and (via JOIN on `id`) the same value for
   `property_listings`. Capitalized for prettier defaults.
3. Flips both columns to NOT NULL.

This migration will get folded into the consolidated initial schema
once the dev DB is reset (no PROD yet). Migration is intentionally
transitional — the backfill default is not part of the long-term
schema.
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "a8c4f3d2e7b5"
down_revision: Union[str, Sequence[str], None] = "c2c206f0a679"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add nullable columns.
    op.add_column(
        "properties",
        sa.Column("title", sa.Text(), nullable=True),
    )
    op.add_column(
        "property_listings",
        sa.Column("title", sa.Text(), nullable=True),
    )

    # 2. Backfill. `typology::text` strips the postgres enum cast so
    # INITCAP can read it; capitalizes "apartment" → "Apartment" so the
    # default reads like a human wrote it. address sits at the end for
    # context. property_listings backfill copies from properties so
    # both tables get identical titles (the projector will overwrite
    # as events flow through).
    op.execute(
        """
        UPDATE properties
           SET title = INITCAP(typology::text) || ' · ' || address
         WHERE title IS NULL
        """
    )
    op.execute(
        """
        UPDATE property_listings AS pl
           SET title = p.title
          FROM properties AS p
         WHERE pl.id = p.id
           AND pl.title IS NULL
        """
    )
    # Any property_listings row whose properties source-of-truth was
    # deleted (or never existed — defensive) gets a static fallback.
    op.execute(
        """
        UPDATE property_listings
           SET title = INITCAP(typology::text) || ' · property'
         WHERE title IS NULL
        """
    )

    # 3. Flip to NOT NULL.
    op.alter_column("properties", "title", nullable=False)
    op.alter_column("property_listings", "title", nullable=False)


def downgrade() -> None:
    op.drop_column("property_listings", "title")
    op.drop_column("properties", "title")
