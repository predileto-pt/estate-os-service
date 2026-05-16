"""add cookies_consent column to sessions

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-16 00:00:01

Adds a `cookies_consent` column to track GDPR consent on the portal
session row. Values: NULL (undecided) | 'accepted' | 'declined'.
A check constraint enforces the allowed values.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("cookies_consent", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_sessions_cookies_consent",
        "sessions",
        "cookies_consent IS NULL OR cookies_consent IN ('accepted', 'declined')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_sessions_cookies_consent", "sessions", type_="check")
    op.drop_column("sessions", "cookies_consent")
