"""add latitude/longitude to properties

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-17

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("properties", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("properties", sa.Column("longitude", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("properties", "longitude")
    op.drop_column("properties", "latitude")
