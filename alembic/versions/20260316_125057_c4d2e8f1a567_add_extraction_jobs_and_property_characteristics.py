"""add extraction_jobs and property characteristics

Revision ID: c4d2e8f1a567
Revises: b3a1e7f2d456
Create Date: 2026-03-16

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c4d2e8f1a567"
down_revision: Union[str, None] = "b3a1e7f2d456"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- Add characteristics JSONB column to properties -----------------------
    op.add_column("properties", sa.Column("characteristics", postgresql.JSONB(), nullable=True))

    # -- Enum for extraction job status ---------------------------------------
    extraction_job_status = postgresql.ENUM(
        "pending",
        "processing",
        "completed",
        "failed",
        name="extraction_job_status",
        create_type=False,
    )
    extraction_job_status.create(op.get_bind(), checkfirst=True)

    # -- extraction_jobs table ------------------------------------------------
    op.create_table(
        "extraction_jobs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("status", extraction_job_status, server_default="pending", nullable=False),
        sa.Column("document_keys", postgresql.JSONB(), nullable=False),
        sa.Column("property_id", sa.UUID(), sa.ForeignKey("properties.id"), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_extraction_jobs_user_id", "extraction_jobs", ["user_id"])

    # -- Trigger for updated_at -----------------------------------------------
    op.execute("""
        CREATE TRIGGER trg_extraction_jobs_updated_at
            BEFORE UPDATE ON extraction_jobs
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)

    # -- RLS (Supabase) -------------------------------------------------------
    op.execute("ALTER TABLE extraction_jobs ENABLE ROW LEVEL SECURITY;")

    op.execute("""
        CREATE POLICY "Service role can manage extraction_jobs"
            ON extraction_jobs FOR ALL USING (auth.role() = 'service_role');
    """)
    op.execute("""
        CREATE POLICY "Users can manage their own extraction_jobs"
            ON extraction_jobs FOR ALL
            USING (user_id = auth.uid())
            WITH CHECK (user_id = auth.uid());
    """)


def downgrade() -> None:
    # -- RLS policies ---------------------------------------------------------
    op.execute(
        'DROP POLICY IF EXISTS "Users can manage their own extraction_jobs" ON extraction_jobs;'
    )
    op.execute(
        'DROP POLICY IF EXISTS "Service role can manage extraction_jobs" ON extraction_jobs;'
    )

    # -- Trigger --------------------------------------------------------------
    op.execute("DROP TRIGGER IF EXISTS trg_extraction_jobs_updated_at ON extraction_jobs;")

    # -- Table ----------------------------------------------------------------
    op.drop_index("idx_extraction_jobs_user_id", "extraction_jobs")
    op.drop_table("extraction_jobs")

    # -- Enum -----------------------------------------------------------------
    op.execute("DROP TYPE IF EXISTS extraction_job_status;")

    # -- Remove characteristics column ----------------------------------------
    op.drop_column("properties", "characteristics")
