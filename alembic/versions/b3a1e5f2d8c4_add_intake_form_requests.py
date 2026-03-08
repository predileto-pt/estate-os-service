"""add intake_form_requests

Revision ID: b3a1e5f2d8c4
Revises: 9f8f4ad7c7ea
Create Date: 2026-03-08

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b3a1e5f2d8c4"
down_revision: Union[str, None] = "9f8f4ad7c7ea"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- Enum -----------------------------------------------------------------
    intake_form_request_status = postgresql.ENUM(
        "pending", "completed", "expired",
        name="intake_form_request_status", create_type=False,
    )
    intake_form_request_status.create(op.get_bind(), checkfirst=True)

    # -- Table ----------------------------------------------------------------
    op.create_table(
        "intake_form_requests",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=False),
        sa.Column("applicant_name", sa.Text(), nullable=False),
        sa.Column("applicant_email", sa.Text(), nullable=False),
        sa.Column("applicant_phone", sa.Text(), nullable=True),
        sa.Column("property_id", sa.Text(), nullable=False),
        sa.Column("status", intake_form_request_status, server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # -- Trigger (reuses existing function) -----------------------------------
    op.execute("""
        CREATE TRIGGER trg_intake_form_requests_updated_at
            BEFORE UPDATE ON intake_form_requests
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)

    # -- RLS ------------------------------------------------------------------
    op.execute("ALTER TABLE intake_form_requests ENABLE ROW LEVEL SECURITY;")

    op.execute("""
        CREATE POLICY "Agencies can view own intake form requests"
            ON intake_form_requests FOR SELECT
            USING (auth.uid() = agency_id);
    """)
    op.execute("""
        CREATE POLICY "Agencies can insert own intake form requests"
            ON intake_form_requests FOR INSERT
            WITH CHECK (auth.uid() = agency_id);
    """)
    op.execute("""
        CREATE POLICY "Agencies can update own intake form requests"
            ON intake_form_requests FOR UPDATE
            USING (auth.uid() = agency_id);
    """)
    op.execute("""
        CREATE POLICY "Public can view intake form requests by link"
            ON intake_form_requests FOR SELECT
            TO anon
            USING (true);
    """)


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS "Public can view intake form requests by link" ON intake_form_requests;')
    op.execute('DROP POLICY IF EXISTS "Agencies can update own intake form requests" ON intake_form_requests;')
    op.execute('DROP POLICY IF EXISTS "Agencies can insert own intake form requests" ON intake_form_requests;')
    op.execute('DROP POLICY IF EXISTS "Agencies can view own intake form requests" ON intake_form_requests;')
    op.execute("DROP TRIGGER IF EXISTS trg_intake_form_requests_updated_at ON intake_form_requests;")
    op.drop_table("intake_form_requests")
    op.execute("DROP TYPE IF EXISTS intake_form_request_status;")
