"""add background_jobs table + tracked_job_id on extraction_jobs

Revision ID: ed01e7809f3d
Revises: b58514282ab5
Create Date: 2026-05-09 12:00:00.000000

ADR-012 implementation. Adds the unified `background_jobs` table the
shared `src/shared/jobs/` infrastructure module reads from / writes to,
plus a nullable `tracked_job_id` column on `extraction_jobs` so the
properties context can link its rich extraction-state row to the unified
tracking row (ADR-012 §8).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "ed01e7809f3d"
down_revision: Union[str, Sequence[str], None] = "b58514282ab5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create background_jobs + indexes + RLS policy + updated_at trigger;
    add tracked_job_id to extraction_jobs."""

    job_kind = sa.Enum(
        "property_document_extraction",
        "property_enrichment",
        "applicant_screening",
        "contract_ingestion",
        "contract_analysis",
        "media_generation_image",
        "media_generation_video",
        name="job_kind",
    )
    job_status = sa.Enum(
        "pending",
        "processing",
        "completed",
        "failed",
        name="job_status",
    )
    job_entity_type = sa.Enum(
        "property",
        "listing",
        "applicant",
        "contract",
        "generated_media",
        name="job_entity_type",
    )

    op.create_table(
        "background_jobs",
        sa.Column(
            "id",
            sa.UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("requested_by_user_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("kind", job_kind, nullable=False),
        sa.Column(
            "status",
            job_status,
            nullable=False,
            server_default=sa.text("'processing'::job_status"),
        ),
        sa.Column("entity_type", job_entity_type, nullable=False),
        # FK-by-id only — no SQL FK; jobs is shared infra and can't reference
        # tables in other contexts (ADR-012 §2).
        sa.Column("entity_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "result_summary",
            sa.dialects.postgresql.JSONB,
            nullable=True,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "idx_background_jobs_org_status_created",
        "background_jobs",
        ["organization_id", "status", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "idx_background_jobs_entity",
        "background_jobs",
        ["entity_type", "entity_id", "kind", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "idx_background_jobs_kind_status_created",
        "background_jobs",
        ["kind", "status", sa.text("created_at DESC")],
        unique=False,
    )

    # Re-uses the existing trigger function defined in the initial migration
    # (`update_updated_at_column`).
    op.execute("""
        CREATE TRIGGER update_background_jobs_updated_at
            BEFORE UPDATE ON background_jobs
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
    """)

    op.execute("ALTER TABLE background_jobs ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY background_jobs_service_role
        ON background_jobs FOR ALL USING (auth.role() = 'service_role');
    """)

    # Link from existing `extraction_jobs` to the new unified row.
    op.add_column(
        "extraction_jobs",
        sa.Column("tracked_job_id", sa.UUID(as_uuid=False), nullable=True),
    )


def downgrade() -> None:
    """Reverse: drop the column on extraction_jobs, then the table + enums."""
    op.drop_column("extraction_jobs", "tracked_job_id")

    op.execute("DROP POLICY IF EXISTS background_jobs_service_role ON background_jobs")
    op.execute("DROP TRIGGER IF EXISTS update_background_jobs_updated_at ON background_jobs")
    op.drop_index("idx_background_jobs_kind_status_created", table_name="background_jobs")
    op.drop_index("idx_background_jobs_entity", table_name="background_jobs")
    op.drop_index("idx_background_jobs_org_status_created", table_name="background_jobs")
    op.drop_table("background_jobs")
    op.execute("DROP TYPE IF EXISTS job_entity_type")
    op.execute("DROP TYPE IF EXISTS job_status")
    op.execute("DROP TYPE IF EXISTS job_kind")
