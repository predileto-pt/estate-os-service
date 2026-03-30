"""make organizations name nullable

Revision ID: e3f4a5b6c7d8
Revises: d2b3c4d5e6f7
Create Date: 2026-03-17

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, None] = "d2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("organizations", "name", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    op.execute("UPDATE organizations SET name = '' WHERE name IS NULL")
    op.alter_column("organizations", "name", existing_type=sa.Text(), nullable=False)
