"""add place_id and google_maps_url to property_amenities

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-03-23 16:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("property_amenities", sa.Column("nearest_place_id", sa.Text(), nullable=True))
    op.add_column(
        "property_amenities", sa.Column("nearest_google_maps_url", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("property_amenities", "nearest_google_maps_url")
    op.drop_column("property_amenities", "nearest_place_id")
