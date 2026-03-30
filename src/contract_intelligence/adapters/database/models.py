from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from contract_intelligence.domain.entities import (
    GeneratedContractStatus,
    ReviewStatus,
    RunStatus,
    SectionStatus,
    TemplateStatus,
    UploadStatus,
)
from shared.database.models import Base


# ---------------------------------------------------------------------------
# Source Documents
# ---------------------------------------------------------------------------


class ContractSourceDocumentModel(Base):
    __tablename__ = "contract_source_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    filename: Mapped[str] = mapped_column(Text, nullable=False)
    storage_url: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    upload_status: Mapped[str] = mapped_column(
        Text, nullable=False, default=UploadStatus.UPLOADED.value
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    parse_runs: Mapped[list[SourceParseRunModel]] = relationship(
        back_populates="source_document", cascade="all, delete-orphan"
    )
    sections: Mapped[list[SourceSectionModel]] = relationship(
        back_populates="source_document", cascade="all, delete-orphan"
    )
    extraction_runs: Mapped[list[SourceExtractionRunModel]] = relationship(
        back_populates="source_document", cascade="all, delete-orphan"
    )
    analysis_runs: Mapped[list[SourceSectionAnalysisRunModel]] = relationship(
        back_populates="source_document", cascade="all, delete-orphan"
    )


class SourceParseRunModel(Base):
    __tablename__ = "contract_source_parse_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contract_source_documents.id", ondelete="CASCADE"),
        nullable=False,
    )

    provider: Mapped[str] = mapped_column(Text, nullable=False, default="reducto")
    provider_job_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_config_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    response_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default=RunStatus.PENDING.value)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    source_document: Mapped[ContractSourceDocumentModel] = relationship(back_populates="parse_runs")


class SourceSectionModel(Base):
    __tablename__ = "contract_source_sections"
    __table_args__ = (
        Index(
            "ix_contract_source_sections_document_sort_order", "source_document_id", "sort_order"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contract_source_documents.id", ondelete="CASCADE"),
        nullable=False,
    )

    section_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    classification_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    review_status: Mapped[str] = mapped_column(
        Text, nullable=False, default=ReviewStatus.PENDING.value
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    source_document: Mapped[ContractSourceDocumentModel] = relationship(back_populates="sections")
    field_evidence: Mapped[list[SourceFieldEvidenceModel]] = relationship(
        back_populates="source_section"
    )
    analyses: Mapped[list[SourceSectionAnalysisModel]] = relationship(
        back_populates="source_section"
    )


class SourceExtractionRunModel(Base):
    __tablename__ = "contract_source_extraction_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contract_source_documents.id", ondelete="CASCADE"),
        nullable=False,
    )

    provider: Mapped[str] = mapped_column(Text, nullable=False, default="reducto")
    provider_job_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    extraction_schema_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    result_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default=RunStatus.PENDING.value)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    source_document: Mapped[ContractSourceDocumentModel] = relationship(
        back_populates="extraction_runs"
    )
    field_evidence: Mapped[list[SourceFieldEvidenceModel]] = relationship(
        back_populates="source_extraction_run", cascade="all, delete-orphan"
    )


class SourceFieldEvidenceModel(Base):
    __tablename__ = "contract_source_field_evidence"
    __table_args__ = (
        Index(
            "ix_contract_source_field_evidence_extraction_field_key",
            "source_extraction_run_id",
            "field_key",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_extraction_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contract_source_extraction_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contract_source_sections.id", ondelete="SET NULL"),
        nullable=True,
    )

    field_key: Mapped[str] = mapped_column(Text, nullable=False)
    field_value_json: Mapped[dict | list | str | int | float | bool | None] = mapped_column(
        JSONB, nullable=True
    )
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    review_status: Mapped[str] = mapped_column(
        Text, nullable=False, default=ReviewStatus.PENDING.value
    )
    corrected_value_json: Mapped[dict | list | str | int | float | bool | None] = mapped_column(
        JSONB, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    source_extraction_run: Mapped[SourceExtractionRunModel] = relationship(
        back_populates="field_evidence"
    )
    source_section: Mapped[SourceSectionModel | None] = relationship(
        back_populates="field_evidence"
    )


class SourceSectionAnalysisRunModel(Base):
    __tablename__ = "contract_source_section_analysis_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contract_source_documents.id", ondelete="CASCADE"),
        nullable=False,
    )

    provider: Mapped[str] = mapped_column(Text, nullable=False, default="openai")
    model_name: Mapped[str] = mapped_column(Text, nullable=False, default="gpt-5.4")
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False, default="v1")
    status: Mapped[str] = mapped_column(Text, nullable=False, default=RunStatus.PENDING.value)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    source_document: Mapped[ContractSourceDocumentModel] = relationship(
        back_populates="analysis_runs"
    )
    analyses: Mapped[list[SourceSectionAnalysisModel]] = relationship(
        back_populates="analysis_run", cascade="all, delete-orphan"
    )


class SourceSectionAnalysisModel(Base):
    __tablename__ = "contract_source_section_analyses"
    __table_args__ = (
        Index(
            "ix_contract_source_section_analyses_run_section",
            "source_section_analysis_run_id",
            "source_section_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_section_analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contract_source_section_analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_section_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contract_source_sections.id", ondelete="CASCADE"),
        nullable=False,
    )

    section_type: Mapped[str] = mapped_column(Text, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_strategy: Mapped[str] = mapped_column(Text, nullable=False)
    review_status: Mapped[str] = mapped_column(
        Text, nullable=False, default=ReviewStatus.PENDING.value
    )
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_section_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_risk_level: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_strategy: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    analysis_run: Mapped[SourceSectionAnalysisRunModel] = relationship(back_populates="analyses")
    source_section: Mapped[SourceSectionModel] = relationship(back_populates="analyses")
    references: Mapped[list[SourceSectionAnalysisReferenceModel]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )


class SourceSectionAnalysisReferenceModel(Base):
    __tablename__ = "contract_source_section_analysis_references"
    __table_args__ = (
        Index(
            "ix_contract_source_section_analysis_refs_analysis_type_key",
            "source_section_analysis_id",
            "reference_type",
            "reference_key",
        ),
        Index(
            "ix_contract_source_section_analysis_refs_type_key", "reference_type", "reference_key"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_section_analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contract_source_section_analyses.id", ondelete="CASCADE"),
        nullable=False,
    )

    reference_type: Mapped[str] = mapped_column(Text, nullable=False)
    reference_key: Mapped[str] = mapped_column(Text, nullable=False)
    display_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    analysis: Mapped[SourceSectionAnalysisModel] = relationship(back_populates="references")


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


class ContractTemplateModel(Base):
    __tablename__ = "contract_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    contract_type: Mapped[str] = mapped_column(Text, nullable=False)
    jurisdiction: Mapped[str] = mapped_column(Text, nullable=False)
    language_code: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default=TemplateStatus.DRAFT.value)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    versions: Mapped[list[ContractTemplateVersionModel]] = relationship(
        back_populates="contract_template", cascade="all, delete-orphan"
    )


class ContractTemplateVersionModel(Base):
    __tablename__ = "contract_template_versions"
    __table_args__ = (
        UniqueConstraint(
            "contract_template_id",
            "version_number",
            name="uq_contract_template_versions_template_version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contract_template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contract_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contract_source_documents.id", ondelete="SET NULL"),
        nullable=True,
    )

    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    render_engine: Mapped[str] = mapped_column(Text, nullable=False, default="jinja")
    schema_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    computed_rules_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(Text, nullable=False, default=TemplateStatus.DRAFT.value)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    contract_template: Mapped[ContractTemplateModel] = relationship(back_populates="versions")
    sections: Mapped[list[TemplateSectionModel]] = relationship(
        back_populates="template_version", cascade="all, delete-orphan"
    )
    field_bindings: Mapped[list[TemplateFieldBindingModel]] = relationship(
        back_populates="template_version", cascade="all, delete-orphan"
    )
    conditions: Mapped[list[TemplateConditionModel]] = relationship(
        back_populates="template_version", cascade="all, delete-orphan"
    )
    party_slots: Mapped[list[TemplatePartySlotModel]] = relationship(
        back_populates="template_version", cascade="all, delete-orphan"
    )


class TemplateSectionModel(Base):
    __tablename__ = "contract_template_sections"
    __table_args__ = (
        Index(
            "ix_contract_template_sections_version_sort_order", "template_version_id", "sort_order"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contract_template_versions.id", ondelete="CASCADE"),
        nullable=False,
    )

    section_key: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    section_type: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_repeatable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_optional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    condition_expression: Mapped[str | None] = mapped_column(Text, nullable=True)
    render_template: Mapped[str] = mapped_column(Text, nullable=False)
    source_text_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default=SectionStatus.DRAFT.value)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    template_version: Mapped[ContractTemplateVersionModel] = relationship(back_populates="sections")


class TemplateFieldBindingModel(Base):
    __tablename__ = "contract_template_field_bindings"
    __table_args__ = (
        Index(
            "ix_contract_template_field_bindings_version_field_key",
            "template_version_id",
            "field_key",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contract_template_versions.id", ondelete="CASCADE"),
        nullable=False,
    )

    template_section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contract_template_sections.id", ondelete="SET NULL"),
        nullable=True,
    )

    field_key: Mapped[str] = mapped_column(Text, nullable=False)
    binding_type: Mapped[str] = mapped_column(Text, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    placeholder_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_value_json: Mapped[dict | list | str | int | float | bool | None] = mapped_column(
        JSONB, nullable=True
    )
    validation_rules_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_hint: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    template_version: Mapped[ContractTemplateVersionModel] = relationship(
        back_populates="field_bindings"
    )


class TemplateConditionModel(Base):
    __tablename__ = "contract_template_conditions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contract_template_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    template_section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contract_template_sections.id", ondelete="SET NULL"),
        nullable=True,
    )

    condition_key: Mapped[str] = mapped_column(Text, nullable=False)
    expression: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    template_version: Mapped[ContractTemplateVersionModel] = relationship(
        back_populates="conditions"
    )


class TemplatePartySlotModel(Base):
    __tablename__ = "contract_template_party_slots"
    __table_args__ = (
        CheckConstraint(
            "min_count >= 0", name="ck_contract_template_party_slots_min_count_nonnegative"
        ),
        CheckConstraint(
            "max_count >= min_count", name="ck_contract_template_party_slots_max_gte_min"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contract_template_versions.id", ondelete="CASCADE"),
        nullable=False,
    )

    role_key: Mapped[str] = mapped_column(Text, nullable=False)
    min_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    display_label_singular: Mapped[str] = mapped_column(Text, nullable=False)
    display_label_plural: Mapped[str] = mapped_column(Text, nullable=False)
    alias_singular: Mapped[str | None] = mapped_column(Text, nullable=True)
    alias_plural: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_intro_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    template_version: Mapped[ContractTemplateVersionModel] = relationship(
        back_populates="party_slots"
    )


# ---------------------------------------------------------------------------
# Generated Contracts
# ---------------------------------------------------------------------------


class GeneratedContractModel(Base):
    __tablename__ = "contract_generated_contracts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contract_template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contract_templates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    template_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contract_template_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    crm_contact_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    crm_property_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default=GeneratedContractStatus.DRAFT.value
    )
    input_payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    rendered_schema_json: Mapped[dict] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    parties: Mapped[list[GeneratedContractPartyModel]] = relationship(
        back_populates="generated_contract", cascade="all, delete-orphan"
    )
    sections: Mapped[list[GeneratedContractSectionModel]] = relationship(
        back_populates="generated_contract", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list[GeneratedContractArtifactModel]] = relationship(
        back_populates="generated_contract", cascade="all, delete-orphan"
    )


class GeneratedContractPartyModel(Base):
    __tablename__ = "contract_generated_contract_parties"
    __table_args__ = (
        Index(
            "ix_contract_generated_contract_parties_contract_role_order",
            "generated_contract_id",
            "role_key",
            "party_order",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    generated_contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contract_generated_contracts.id", ondelete="CASCADE"),
        nullable=False,
    )

    role_key: Mapped[str] = mapped_column(Text, nullable=False)
    party_order: Mapped[int] = mapped_column(Integer, nullable=False)
    party_type: Mapped[str] = mapped_column(Text, nullable=False, default="individual")
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    tax_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_expiry: Mapped[str | None] = mapped_column(Text, nullable=True)
    address_line_1: Mapped[str | None] = mapped_column(Text, nullable=True)
    address_line_2: Mapped[str | None] = mapped_column(Text, nullable=True)
    postal_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(Text, nullable=True)
    country_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    generated_contract: Mapped[GeneratedContractModel] = relationship(back_populates="parties")


class GeneratedContractSectionModel(Base):
    __tablename__ = "contract_generated_contract_sections"
    __table_args__ = (
        Index(
            "ix_contract_generated_contract_sections_contract_sort_order",
            "generated_contract_id",
            "sort_order",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    generated_contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contract_generated_contracts.id", ondelete="CASCADE"),
        nullable=False,
    )
    template_section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contract_template_sections.id", ondelete="SET NULL"),
        nullable=True,
    )

    section_key: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    rendered_text: Mapped[str] = mapped_column(Text, nullable=False)
    render_state: Mapped[str] = mapped_column(Text, nullable=False, default="rendered")
    skip_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    generated_contract: Mapped[GeneratedContractModel] = relationship(back_populates="sections")


class GeneratedContractArtifactModel(Base):
    __tablename__ = "contract_generated_contract_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    generated_contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contract_generated_contracts.id", ondelete="CASCADE"),
        nullable=False,
    )

    artifact_type: Mapped[str] = mapped_column(Text, nullable=False)
    storage_url: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    generated_contract: Mapped[GeneratedContractModel] = relationship(back_populates="artifacts")
