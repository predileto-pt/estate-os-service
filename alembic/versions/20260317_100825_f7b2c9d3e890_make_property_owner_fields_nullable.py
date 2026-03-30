"""make property_owner fields nullable

Revision ID: f7b2c9d3e890
Revises: e6f4a1b3c789
Create Date: 2026-03-16

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f7b2c9d3e890"
down_revision: Union[str, None] = "e6f4a1b3c789"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("property_owners", "civil_status", nullable=True)
    op.alter_column("property_owners", "document_type", nullable=True)
    op.alter_column("property_owners", "document_id", nullable=True)
    op.alter_column("property_owners", "issued_by", nullable=True)
    op.alter_column("property_owners", "date_of_birth", nullable=True)


def downgrade() -> None:
    op.alter_column("property_owners", "date_of_birth", nullable=False)
    op.alter_column("property_owners", "issued_by", nullable=False)
    op.alter_column("property_owners", "document_id", nullable=False)
    op.alter_column("property_owners", "document_type", nullable=False)
    op.alter_column("property_owners", "civil_status", nullable=False)
