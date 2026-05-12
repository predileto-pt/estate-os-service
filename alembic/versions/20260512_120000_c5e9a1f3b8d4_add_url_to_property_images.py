"""add url column to property_images

Revision ID: c5e9a1f3b8d4
Revises: b9d5e8c3f1a2
Create Date: 2026-05-12 12:00:00

Spec: image URL stored at upload time (public bucket → no read-time presign).
The column is nullable so the add is safe on the live table; new uploads
populate it via `RecordPropertyImage`. Existing rows are backfilled by a
separate one-shot CLI (or stay empty until the next re-upload).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c5e9a1f3b8d4"
down_revision: Union[str, Sequence[str], None] = "b9d5e8c3f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("property_images", sa.Column("url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("property_images", "url")
