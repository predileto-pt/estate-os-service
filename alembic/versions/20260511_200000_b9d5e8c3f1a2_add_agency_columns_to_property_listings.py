"""add agency_name/email/phone columns to property_listings

Revision ID: b9d5e8c3f1a2
Revises: a8c4f3d2e7b5
Create Date: 2026-05-11 20:00:00

Spec: 2026-05-listings-agency-contact.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b9d5e8c3f1a2"
down_revision: Union[str, Sequence[str], None] = "a8c4f3d2e7b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("property_listings", sa.Column("agency_name", sa.Text(), nullable=True))
    op.add_column("property_listings", sa.Column("agency_email", sa.Text(), nullable=True))
    op.add_column("property_listings", sa.Column("agency_phone", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("property_listings", "agency_phone")
    op.drop_column("property_listings", "agency_email")
    op.drop_column("property_listings", "agency_name")
