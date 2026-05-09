"""property_listings: full images + prices lists + floor + parking_spaces

Revision ID: c2c206f0a679
Revises: 4f1c8b2d9e30
Create Date: 2026-05-09 23:00:00.000000

Spec: collapse the legacy `ListingRepository` (read mapping over the
live `properties` table) into `PropertyListingRepository` (the
projection over `property_listings`). The route currently returns the
full image + price list via the legacy repo; the projection only
carried `min_price` and `first_image_s3_key` denormalized
convenience columns. To migrate the route without losing response
fidelity, the projection absorbs the full lists.

Adds four columns:
  - `images` jsonb NOT NULL DEFAULT '[]' — list of
    `{id, s3_key, display_order}` per the snapshot shape.
  - `prices` jsonb NOT NULL DEFAULT '[]' — list of
    `{amount, listing_type}` per the snapshot shape.
  - `floor` integer nullable — was a `PropertyCharacteristics`
    field rendered into `PropertyCharacteristicsResponse.floor`.
  - `parking_spaces` integer nullable — same story.

Existing rows default to empty lists; the next `PROPERTY_UPDATED.v1`
re-projects them from the snapshot. For stagnant rows (no further
events), a separate backfill spec re-fires the events.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c2c206f0a679"
down_revision: Union[str, Sequence[str], None] = "4f1c8b2d9e30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "property_listings",
        sa.Column(
            "images",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "property_listings",
        sa.Column(
            "prices",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "property_listings",
        sa.Column("floor", sa.Integer(), nullable=True),
    )
    op.add_column(
        "property_listings",
        sa.Column("parking_spaces", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("property_listings", "parking_spaces")
    op.drop_column("property_listings", "floor")
    op.drop_column("property_listings", "prices")
    op.drop_column("property_listings", "images")
