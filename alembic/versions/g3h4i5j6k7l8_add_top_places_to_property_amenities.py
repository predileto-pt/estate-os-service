"""add top_places to property_amenities

Revision ID: g3h4i5j6k7l8
Revises: f2a3b4c5d6e7
Create Date: 2026-03-23 17:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = "g3h4i5j6k7l8"
down_revision: Union[str, Sequence[str], None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("property_amenities", sa.Column("top_places", JSONB, nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("property_amenities", "top_places")
