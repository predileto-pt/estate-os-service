"""add document_contents table

Revision ID: a8c3d4e5f901
Revises: f7b2c9d3e890
Create Date: 2026-03-16

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8c3d4e5f901"
down_revision: Union[str, None] = "f7b2c9d3e890"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_contents",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "extraction_job_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            sa.ForeignKey("extraction_jobs.id"),
            nullable=False,
        ),
        sa.Column("document_index", sa.Integer, nullable=False),
        sa.Column("document_key", sa.Text, nullable=False),
        sa.Column("parsed_text", sa.Text, nullable=False),
        sa.Column("category", sa.Text, nullable=True),
        sa.Column("document_subtype", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("idx_document_contents_job_id", "document_contents", ["extraction_job_id"])

    # RLS
    op.execute("ALTER TABLE document_contents ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY document_contents_user_isolation ON document_contents
        FOR ALL
        USING (
            extraction_job_id IN (
                SELECT id FROM extraction_jobs WHERE user_id = auth.uid()
            )
        )
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS document_contents_user_isolation ON document_contents")
    op.drop_index("idx_document_contents_job_id", table_name="document_contents")
    op.drop_table("document_contents")
