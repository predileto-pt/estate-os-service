"""add retrying to extraction_job_status enum

Revision ID: b9d4e5f6a012
Revises: a8c3d4e5f901
Create Date: 2026-03-17

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b9d4e5f6a012"
down_revision: Union[str, None] = "a8c3d4e5f901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE extraction_job_status ADD VALUE IF NOT EXISTS 'retrying'")


def downgrade() -> None:
    # PostgreSQL does not support removing values from enums.
    # To fully reverse this, you would need to recreate the type without 'retrying'.
    pass
