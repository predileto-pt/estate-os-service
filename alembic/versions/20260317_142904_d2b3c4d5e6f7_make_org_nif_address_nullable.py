"""make organizations nif and address nullable

Revision ID: d2b3c4d5e6f7
Revises: c1a2b3c4d5e6
Create Date: 2026-03-17

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d2b3c4d5e6f7"
down_revision: Union[str, None] = "c1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("organizations", "nif", existing_type=sa.Text(), nullable=True)
    op.alter_column("organizations", "address", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    op.execute("UPDATE organizations SET nif = '' WHERE nif IS NULL")
    op.execute("UPDATE organizations SET address = '' WHERE address IS NULL")
    op.alter_column("organizations", "nif", existing_type=sa.Text(), nullable=False)
    op.alter_column("organizations", "address", existing_type=sa.Text(), nullable=False)
