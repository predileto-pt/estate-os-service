"""add property fields and applicant columns

Revision ID: c7d2f8a1b3e5
Revises: b3a1e5f2d8c4
Create Date: 2026-03-08

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c7d2f8a1b3e5"
down_revision: Union[str, None] = "b3a1e5f2d8c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- intake_form_requests: property metadata --------------------------------
    op.add_column("intake_form_requests", sa.Column("property_title", sa.Text(), nullable=True))
    op.add_column("intake_form_requests", sa.Column("property_price", sa.Float(), nullable=True))
    op.add_column("intake_form_requests", sa.Column("property_address", sa.Text(), nullable=True))

    # -- applicants: new columns ------------------------------------------------
    op.add_column("applicants", sa.Column("visitor_nif", sa.Text(), nullable=True))
    op.add_column(
        "applicants",
        sa.Column("visitor_date_of_birth", sa.Date(), nullable=True),
    )
    op.add_column("applicants", sa.Column("property_price", sa.Float(), nullable=True))
    op.add_column("applicants", sa.Column("property_address", sa.Text(), nullable=True))
    op.add_column("applicants", sa.Column("justification", sa.Text(), nullable=True))
    op.add_column(
        "applicants",
        sa.Column("income_records", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "applicants",
        sa.Column("form_request_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "applicants",
        sa.Column("screening_applicant_id", sa.UUID(), nullable=True),
    )

    op.create_index(
        "idx_applicants_form_request_id",
        "applicants",
        ["form_request_id"],
    )

    # -- RLS: service_role can manage applicants (for SQS worker) ---------------
    op.execute("""
        CREATE POLICY "Service role can manage applicants"
            ON applicants FOR ALL
            USING (auth.role() = 'service_role')
            WITH CHECK (auth.role() = 'service_role');
    """)
    op.execute("""
        CREATE POLICY "Service role can manage intake form requests"
            ON intake_form_requests FOR ALL
            USING (auth.role() = 'service_role')
            WITH CHECK (auth.role() = 'service_role');
    """)


def downgrade() -> None:
    op.execute(
        'DROP POLICY IF EXISTS "Service role can manage intake form requests"'
        " ON intake_form_requests;"
    )
    op.execute('DROP POLICY IF EXISTS "Service role can manage applicants" ON applicants;')
    op.drop_index("idx_applicants_form_request_id", table_name="applicants")
    op.drop_column("applicants", "screening_applicant_id")
    op.drop_column("applicants", "form_request_id")
    op.drop_column("applicants", "income_records")
    op.drop_column("applicants", "justification")
    op.drop_column("applicants", "property_address")
    op.drop_column("applicants", "property_price")
    op.drop_column("applicants", "visitor_date_of_birth")
    op.drop_column("applicants", "visitor_nif")
    op.drop_column("intake_form_requests", "property_address")
    op.drop_column("intake_form_requests", "property_price")
    op.drop_column("intake_form_requests", "property_title")
