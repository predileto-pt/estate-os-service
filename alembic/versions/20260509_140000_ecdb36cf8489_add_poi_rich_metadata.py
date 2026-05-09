"""add address, image_urls, reviews to property_pois

Revision ID: ecdb36cf8489
Revises: ed01e7809f3d
Create Date: 2026-05-09 14:00:00.000000

Spec `2026-05-poi-rich-metadata`. Phase 2 of POI enrichment writes:
  - `address` (text, nullable) — Google `formatted_address`
  - `image_urls` (jsonb, NOT NULL default `'[]'::jsonb`) — up to 5 resolved CDN URLs
  - `reviews` (jsonb, nullable) — up to 5 review objects, NULL for blacklisted categories
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "ecdb36cf8489"
down_revision: Union[str, Sequence[str], None] = "ed01e7809f3d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "property_pois",
        sa.Column("address", sa.Text(), nullable=True),
    )
    op.add_column(
        "property_pois",
        sa.Column(
            "image_urls",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "property_pois",
        sa.Column(
            "reviews",
            sa.dialects.postgresql.JSONB,
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("property_pois", "reviews")
    op.drop_column("property_pois", "image_urls")
    op.drop_column("property_pois", "address")
