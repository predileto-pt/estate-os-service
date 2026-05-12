"""add email + phone columns to organizations

Revision ID: d6f7b2a4c8e1
Revises: c5e9a1f3b8d4
Create Date: 2026-05-12 18:00:00

Organization now carries a contact email and phone (country code +
number, same shape as User.phone). All three columns are nullable so
the add is safe on the live table; the new PATCH /organizations/{id}
endpoint populates them when the agency owner edits the org.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d6f7b2a4c8e1"
down_revision: Union[str, Sequence[str], None] = "c5e9a1f3b8d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("email", sa.Text(), nullable=True))
    op.add_column(
        "organizations", sa.Column("phone_country_code", sa.Text(), nullable=True)
    )
    op.add_column("organizations", sa.Column("phone_number", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("organizations", "phone_number")
    op.drop_column("organizations", "phone_country_code")
    op.drop_column("organizations", "email")
