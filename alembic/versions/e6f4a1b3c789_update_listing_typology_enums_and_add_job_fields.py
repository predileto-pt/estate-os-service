"""update listing_type and typology enums, add listing_type and typology to extraction_jobs

Revision ID: e6f4a1b3c789
Revises: d5e3f9a2b678
Create Date: 2026-03-16

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e6f4a1b3c789"
down_revision: Union[str, None] = "d5e3f9a2b678"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- Rename listing_type enum values: rent → purchase ----------------------
    op.execute("ALTER TYPE listing_type RENAME VALUE 'rent' TO 'purchase'")

    # -- Recreate typology enum: replace old values with new ones -------------
    # Postgres doesn't support RENAME VALUE before v10 or removing values,
    # so we recreate the enum.
    op.execute("ALTER TYPE typology RENAME TO typology_old")
    op.execute("CREATE TYPE typology AS ENUM ('house', 'apartment', 'land', 'ruin')")
    op.execute(
        "ALTER TABLE properties ALTER COLUMN typology TYPE typology USING typology::text::typology"
    )
    op.execute("DROP TYPE typology_old")

    # -- Add listing_type and typology columns to extraction_jobs -------------
    op.add_column("extraction_jobs", sa.Column("listing_type", sa.Text(), nullable=True))
    op.add_column("extraction_jobs", sa.Column("typology", sa.Text(), nullable=True))


def downgrade() -> None:
    # -- Remove extraction_jobs columns ----------------------------------------
    op.drop_column("extraction_jobs", "typology")
    op.drop_column("extraction_jobs", "listing_type")

    # -- Restore typology enum ------------------------------------------------
    op.execute("ALTER TYPE typology RENAME TO typology_old")
    op.execute("CREATE TYPE typology AS ENUM ('apartment', 'house', 'land', 'commercial')")
    op.execute(
        "ALTER TABLE properties ALTER COLUMN typology TYPE typology USING typology::text::typology"
    )
    op.execute("DROP TYPE typology_old")

    # -- Restore listing_type enum: purchase → rent ----------------------------
    op.execute("ALTER TYPE listing_type RENAME VALUE 'purchase' TO 'rent'")
