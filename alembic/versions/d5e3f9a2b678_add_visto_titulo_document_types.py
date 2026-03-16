"""add visto_residencia and titulo_residencia document types

Revision ID: d5e3f9a2b678
Revises: c4d2e8f1a567
Create Date: 2026-03-16

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5e3f9a2b678"
down_revision: Union[str, None] = "c4d2e8f1a567"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE document_type ADD VALUE IF NOT EXISTS 'visto_residencia'")
    op.execute("ALTER TYPE document_type ADD VALUE IF NOT EXISTS 'titulo_residencia'")


def downgrade() -> None:
    pass
