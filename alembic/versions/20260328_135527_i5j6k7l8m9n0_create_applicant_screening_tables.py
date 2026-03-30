"""create applicant screening tables

Revision ID: i5j6k7l8m9n0
Revises: h4i5j6k7l8m9
Create Date: 2026-03-27 18:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "i5j6k7l8m9n0"
down_revision: Union[str, None] = "h4i5j6k7l8m9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Applicants
    op.create_table(
        "applicant_applicants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("nif", sa.String(512), nullable=False),
        sa.Column("nif_hash", sa.String(64), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("form_request_id", sa.Uuid(), nullable=False),
        sa.Column("listing_type", sa.String(20), nullable=False),
        sa.Column("property_type", sa.String(20), nullable=True),
        sa.Column("phone", sa.String(30), nullable=True),
        sa.Column("property_value", sa.Float(), nullable=True),
        sa.Column("monthly_rent", sa.Float(), nullable=True),
        sa.Column("property_title", sa.String(255), nullable=False, server_default="n/a"),
        sa.Column("property_address", sa.String(500), nullable=False, server_default="n/a"),
        sa.UniqueConstraint("nif_hash", "form_request_id", name="uq_applicants_nif_form_request"),
    )

    # Documents
    op.create_table(
        "applicant_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("applicant_id", sa.Uuid(), sa.ForeignKey("applicant_applicants.id"), nullable=False),
        sa.Column("s3_key", sa.String(512), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("document_type", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reducto_document_id", sa.String(255), nullable=True),
    )

    # Extracted Data
    op.create_table(
        "applicant_extracted_data",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("applicant_documents.id"), nullable=False, unique=True),
        sa.Column("extracted_content", sa.JSON(), nullable=False),
        sa.Column("extraction_status", sa.String(20), nullable=False),
    )

    # Screening Reports
    op.create_table(
        "screening_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("applicant_id", sa.Uuid(), sa.ForeignKey("applicant_applicants.id"), nullable=False),
        sa.Column("risk_level", sa.String(10), nullable=False),
        sa.Column("identity_verified", sa.Boolean(), nullable=False),
        sa.Column("income_verified", sa.Boolean(), nullable=False),
        sa.Column("dti_ratio", sa.Float(), nullable=False),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("listing_type", sa.String(20), nullable=False),
        sa.Column("property_type", sa.String(20), nullable=True),
        sa.Column("average_monthly_income", sa.Float(), nullable=False),
    )

    # Events
    op.create_table(
        "applicant_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("applicant_id", sa.Uuid(), sa.ForeignKey("applicant_applicants.id"), nullable=False, index=True),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Intake Form Requests
    op.create_table(
        "applicant_intake_form_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("applicant_name", sa.String(255), nullable=False),
        sa.Column("applicant_email", sa.String(255), nullable=False),
        sa.Column("applicant_phone", sa.String(50), nullable=True),
        sa.Column("property_id", sa.String(255), nullable=False),
        sa.Column("listing_type", sa.String(20), nullable=False),
        sa.Column("property_type", sa.String(20), nullable=True),
        sa.Column("property_title", sa.String(255), nullable=True),
        sa.Column("property_price", sa.Float(), nullable=True),
        sa.Column("property_address", sa.String(512), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Submissions
    op.create_table(
        "applicant_submissions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("applicant_id", sa.Uuid(), sa.ForeignKey("applicant_applicants.id"), nullable=True),
        sa.Column("form_request_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("terms_accepted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("applicant_submissions")
    op.drop_table("applicant_intake_form_requests")
    op.drop_table("applicant_events")
    op.drop_table("screening_reports")
    op.drop_table("applicant_extracted_data")
    op.drop_table("applicant_documents")
    op.drop_table("applicant_applicants")
