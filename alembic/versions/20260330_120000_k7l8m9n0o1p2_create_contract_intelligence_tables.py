"""create contract intelligence tables

Revision ID: k7l8m9n0o1p2
Revises: j6k7l8m9n0o1
Create Date: 2026-03-30 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "k7l8m9n0o1p2"
down_revision: Union[str, Sequence[str], None] = "j6k7l8m9n0o1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Source Document aggregate ---

    op.create_table(
        "contract_source_documents",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("organization_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("storage_url", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("language_code", sa.String(10), nullable=True),
        sa.Column("document_hash", sa.String(64), nullable=False),
        sa.Column("upload_status", sa.String(20), server_default="uploaded", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("document_hash", name="uq_contract_source_documents_hash"),
    )
    op.create_index("idx_contract_source_documents_org", "contract_source_documents", ["organization_id"])

    op.create_table(
        "contract_source_parse_runs",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("source_document_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("provider", sa.String(50), server_default="reducto", nullable=False),
        sa.Column("provider_job_id", sa.Text(), nullable=True),
        sa.Column("parse_config_json", sa.dialects.postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("response_json", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["source_document_id"], ["contract_source_documents.id"]),
    )
    op.create_index("idx_contract_source_parse_runs_doc", "contract_source_parse_runs", ["source_document_id"])

    op.create_table(
        "contract_source_sections",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("source_document_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("section_key", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("normalized_text", sa.Text(), nullable=True),
        sa.Column("classification_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("review_status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_document_id"], ["contract_source_documents.id"]),
    )
    op.create_index("idx_contract_source_sections_doc_order", "contract_source_sections", ["source_document_id", "sort_order"])

    op.create_table(
        "contract_source_extraction_runs",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("source_document_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("provider", sa.String(50), server_default="reducto", nullable=False),
        sa.Column("provider_job_id", sa.Text(), nullable=True),
        sa.Column("schema_version", sa.String(50), nullable=False),
        sa.Column("extraction_schema_json", sa.dialects.postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("result_json", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["source_document_id"], ["contract_source_documents.id"]),
    )
    op.create_index("idx_contract_source_extraction_runs_doc", "contract_source_extraction_runs", ["source_document_id"])

    op.create_table(
        "contract_source_field_evidence",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("source_extraction_run_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("source_section_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("field_key", sa.String(100), nullable=False),
        sa.Column("field_value_json", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("review_status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("corrected_value_json", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_extraction_run_id"], ["contract_source_extraction_runs.id"]),
        sa.ForeignKeyConstraint(["source_section_id"], ["contract_source_sections.id"]),
    )
    op.create_index("idx_contract_source_field_evidence_run_key", "contract_source_field_evidence", ["source_extraction_run_id", "field_key"])

    op.create_table(
        "contract_source_section_analysis_runs",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("source_document_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("provider", sa.String(50), server_default="openai", nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["source_document_id"], ["contract_source_documents.id"]),
    )
    op.create_index("idx_contract_analysis_runs_doc", "contract_source_section_analysis_runs", ["source_document_id"])

    op.create_table(
        "contract_source_section_analyses",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("source_section_analysis_run_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("source_section_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("section_type", sa.String(30), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("risk_level", sa.String(10), nullable=False),
        sa.Column("recommended_strategy", sa.String(30), nullable=False),
        sa.Column("review_status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("corrected_section_type", sa.String(30), nullable=True),
        sa.Column("corrected_risk_level", sa.String(10), nullable=True),
        sa.Column("corrected_strategy", sa.String(30), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_section_analysis_run_id"], ["contract_source_section_analysis_runs.id"]),
        sa.ForeignKeyConstraint(["source_section_id"], ["contract_source_sections.id"]),
    )
    op.create_index("idx_contract_analyses_run_section", "contract_source_section_analyses", ["source_section_analysis_run_id", "source_section_id"])

    op.create_table(
        "contract_source_section_analysis_references",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("source_section_analysis_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("reference_type", sa.String(20), nullable=False),
        sa.Column("reference_key", sa.String(100), nullable=False),
        sa.Column("display_label", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_section_analysis_id"], ["contract_source_section_analyses.id"]),
    )
    op.create_index("idx_contract_analysis_refs", "contract_source_section_analysis_references", ["source_section_analysis_id"])

    # --- Template aggregate ---

    op.create_table(
        "contract_templates",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("contract_type", sa.String(50), nullable=False),
        sa.Column("jurisdiction", sa.String(50), nullable=False),
        sa.Column("language_code", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), server_default="draft", nullable=False),
        sa.Column("current_version_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("key", name="uq_contract_templates_key"),
    )

    op.create_table(
        "contract_template_versions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("contract_template_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("source_document_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("render_engine", sa.String(20), server_default="jinja", nullable=False),
        sa.Column("schema_json", sa.dialects.postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("computed_rules_json", sa.dialects.postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("status", sa.String(20), server_default="draft", nullable=False),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.dialects.postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("approved_by", sa.dialects.postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["contract_template_id"], ["contract_templates.id"]),
        sa.ForeignKeyConstraint(["source_document_id"], ["contract_source_documents.id"]),
        sa.UniqueConstraint("contract_template_id", "version_number", name="uq_contract_template_versions_num"),
    )

    op.create_table(
        "contract_template_sections",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("template_version_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("section_key", sa.String(100), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("section_type", sa.String(30), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_repeatable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_optional", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("condition_expression", sa.Text(), nullable=True),
        sa.Column("render_template", sa.Text(), nullable=False),
        sa.Column("source_text_snapshot", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), server_default="draft", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["template_version_id"], ["contract_template_versions.id"]),
    )
    op.create_index("idx_contract_template_sections_version", "contract_template_sections", ["template_version_id", "sort_order"])

    op.create_table(
        "contract_template_field_bindings",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("template_version_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("template_section_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("field_key", sa.String(100), nullable=False),
        sa.Column("binding_type", sa.String(50), nullable=False),
        sa.Column("required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("placeholder_label", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("default_value_json", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("validation_rules_json", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("source_hint", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["template_version_id"], ["contract_template_versions.id"]),
        sa.ForeignKeyConstraint(["template_section_id"], ["contract_template_sections.id"]),
    )
    op.create_index("idx_contract_field_bindings_version_key", "contract_template_field_bindings", ["template_version_id", "field_key"])

    op.create_table(
        "contract_template_conditions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("template_version_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("template_section_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("condition_key", sa.String(100), nullable=False),
        sa.Column("expression", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["template_version_id"], ["contract_template_versions.id"]),
        sa.ForeignKeyConstraint(["template_section_id"], ["contract_template_sections.id"]),
    )

    op.create_table(
        "contract_template_party_slots",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("template_version_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("role_key", sa.String(50), nullable=False),
        sa.Column("min_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("display_label_singular", sa.Text(), nullable=False),
        sa.Column("display_label_plural", sa.Text(), nullable=False),
        sa.Column("alias_singular", sa.Text(), nullable=True),
        sa.Column("alias_plural", sa.Text(), nullable=True),
        sa.Column("section_intro_label", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["template_version_id"], ["contract_template_versions.id"]),
        sa.CheckConstraint("min_count >= 0", name="ck_contract_party_slots_min"),
        sa.CheckConstraint("max_count >= min_count", name="ck_contract_party_slots_max"),
    )

    # --- Generated Contract aggregate ---

    op.create_table(
        "contract_generated_contracts",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("contract_template_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("template_version_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("organization_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("crm_contact_id", sa.String(100), nullable=True),
        sa.Column("crm_property_id", sa.String(100), nullable=True),
        sa.Column("status", sa.String(20), server_default="draft", nullable=False),
        sa.Column("input_payload_json", sa.dialects.postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("rendered_schema_json", sa.dialects.postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["contract_template_id"], ["contract_templates.id"]),
        sa.ForeignKeyConstraint(["template_version_id"], ["contract_template_versions.id"]),
    )
    op.create_index("idx_contract_generated_contracts_org", "contract_generated_contracts", ["organization_id"])

    op.create_table(
        "contract_generated_contract_parties",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("generated_contract_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("role_key", sa.String(50), nullable=False),
        sa.Column("party_order", sa.Integer(), nullable=False),
        sa.Column("party_type", sa.String(20), server_default="individual", nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("tax_id", sa.String(50), nullable=True),
        sa.Column("document_type", sa.String(50), nullable=True),
        sa.Column("document_number", sa.String(50), nullable=True),
        sa.Column("document_expiry", sa.String(20), nullable=True),
        sa.Column("address_line_1", sa.Text(), nullable=True),
        sa.Column("address_line_2", sa.Text(), nullable=True),
        sa.Column("postal_code", sa.String(20), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("country_code", sa.String(3), nullable=True),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["generated_contract_id"], ["contract_generated_contracts.id"]),
    )
    op.create_index("idx_contract_gen_parties", "contract_generated_contract_parties", ["generated_contract_id", "role_key", "party_order"])

    op.create_table(
        "contract_generated_contract_sections",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("generated_contract_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("template_section_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("section_key", sa.String(100), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("rendered_text", sa.Text(), nullable=False),
        sa.Column("render_state", sa.String(20), server_default="rendered", nullable=False),
        sa.Column("skip_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["generated_contract_id"], ["contract_generated_contracts.id"]),
        sa.ForeignKeyConstraint(["template_section_id"], ["contract_template_sections.id"]),
    )
    op.create_index("idx_contract_gen_sections", "contract_generated_contract_sections", ["generated_contract_id", "sort_order"])

    op.create_table(
        "contract_generated_contract_artifacts",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("generated_contract_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("artifact_type", sa.String(20), nullable=False),
        sa.Column("storage_url", sa.Text(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["generated_contract_id"], ["contract_generated_contracts.id"]),
    )


def downgrade() -> None:
    op.drop_table("contract_generated_contract_artifacts")
    op.drop_index("idx_contract_gen_sections", table_name="contract_generated_contract_sections")
    op.drop_table("contract_generated_contract_sections")
    op.drop_index("idx_contract_gen_parties", table_name="contract_generated_contract_parties")
    op.drop_table("contract_generated_contract_parties")
    op.drop_index("idx_contract_generated_contracts_org", table_name="contract_generated_contracts")
    op.drop_table("contract_generated_contracts")
    op.drop_table("contract_template_party_slots")
    op.drop_table("contract_template_conditions")
    op.drop_index("idx_contract_field_bindings_version_key", table_name="contract_template_field_bindings")
    op.drop_table("contract_template_field_bindings")
    op.drop_index("idx_contract_template_sections_version", table_name="contract_template_sections")
    op.drop_table("contract_template_sections")
    op.drop_table("contract_template_versions")
    op.drop_table("contract_templates")
    op.drop_index("idx_contract_analysis_refs", table_name="contract_source_section_analysis_references")
    op.drop_table("contract_source_section_analysis_references")
    op.drop_index("idx_contract_analyses_run_section", table_name="contract_source_section_analyses")
    op.drop_table("contract_source_section_analyses")
    op.drop_index("idx_contract_analysis_runs_doc", table_name="contract_source_section_analysis_runs")
    op.drop_table("contract_source_section_analysis_runs")
    op.drop_index("idx_contract_source_field_evidence_run_key", table_name="contract_source_field_evidence")
    op.drop_table("contract_source_field_evidence")
    op.drop_index("idx_contract_source_extraction_runs_doc", table_name="contract_source_extraction_runs")
    op.drop_table("contract_source_extraction_runs")
    op.drop_index("idx_contract_source_sections_doc_order", table_name="contract_source_sections")
    op.drop_table("contract_source_sections")
    op.drop_index("idx_contract_source_parse_runs_doc", table_name="contract_source_parse_runs")
    op.drop_table("contract_source_parse_runs")
    op.drop_index("idx_contract_source_documents_org", table_name="contract_source_documents")
    op.drop_table("contract_source_documents")
