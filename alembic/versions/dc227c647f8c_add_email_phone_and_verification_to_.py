"""Add email phone and verification to property owners

Revision ID: dc227c647f8c
Revises: d4e5f6a7b8c9
Create Date: 2026-03-18 06:06:06.330097

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "dc227c647f8c"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("property_owners", sa.Column("email", sa.Text(), nullable=True))
    op.add_column("property_owners", sa.Column("phone_number", sa.Text(), nullable=True))
    op.add_column(
        "property_owners",
        sa.Column("email_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "property_owners",
        sa.Column("phone_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("property_owners", "phone_verified")
    op.drop_column("property_owners", "email_verified")
    op.drop_column("property_owners", "phone_number")
    op.drop_column("property_owners", "email")
