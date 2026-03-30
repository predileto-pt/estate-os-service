from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from contract_intelligence.domain.entities.source_document import (
    AnalysisReferenceType,
    RecommendedStrategy,
    ReviewStatus,
    RiskLevel,
    RunStatus,
    SectionType,
)

# ---------------------------------------------------------------------------
# Read DTOs (API responses)
# ---------------------------------------------------------------------------


class SourceSectionAnalysisReferenceRead(BaseModel):
    id: uuid.UUID
    reference_type: AnalysisReferenceType
    reference_key: str
    display_label: str | None = None
    confidence: Decimal | None = None
    created_at: datetime


class SourceSectionAnalysisRead(BaseModel):
    id: uuid.UUID
    source_section_analysis_run_id: uuid.UUID
    source_section_id: uuid.UUID
    section_type: SectionType
    reasoning: str
    risk_level: RiskLevel
    recommended_strategy: RecommendedStrategy
    review_status: ReviewStatus
    review_notes: str | None = None
    corrected_section_type: SectionType | None = None
    corrected_risk_level: RiskLevel | None = None
    corrected_strategy: RecommendedStrategy | None = None
    created_at: datetime
    updated_at: datetime
    references: list[SourceSectionAnalysisReferenceRead] = []


class SourceSectionAnalysisRunRead(BaseModel):
    id: uuid.UUID
    source_document_id: uuid.UUID
    provider: str
    model_name: str
    prompt_version: str
    status: RunStatus
    created_at: datetime
    completed_at: datetime | None = None


class SourceSectionAnalysisBundleRead(BaseModel):
    analysis_run: SourceSectionAnalysisRunRead
    analyses: list[SourceSectionAnalysisRead] = []


# ---------------------------------------------------------------------------
# Review update request (UI corrections)
# ---------------------------------------------------------------------------


class UpdateSourceSectionAnalysisReviewRequest(BaseModel):
    review_status: ReviewStatus
    review_notes: str | None = None
    corrected_section_type: SectionType | None = None
    corrected_risk_level: RiskLevel | None = None
    corrected_strategy: RecommendedStrategy | None = None


# ---------------------------------------------------------------------------
# LangChain structured output models (LLM response parsing)
# ---------------------------------------------------------------------------


class AnalysisReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_type: AnalysisReferenceType = Field(
        description="Whether this reference is a field or condition."
    )
    reference_key: str = Field(description="The key identifying the referenced field or condition.")
    display_label: str | None = Field(
        default=None, description="Human-readable label for the reference."
    )
    confidence: Decimal | None = Field(
        default=None, description="Confidence score for this reference, between 0 and 1."
    )


class SectionAnalysisOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_section_id: uuid.UUID = Field(
        description="The UUID of the source section being analysed."
    )
    section_type: SectionType = Field(description="Classification of the section content type.")
    reasoning: str = Field(description="Explanation of why this classification was chosen.")
    risk_level: RiskLevel = Field(
        description="Risk level associated with incorrect rendering of this section."
    )
    recommended_strategy: RecommendedStrategy = Field(
        description="Recommended rendering strategy for template generation."
    )
    references: list[AnalysisReference] = Field(
        default=[], description="Fields and conditions referenced by this section."
    )


class SourceSectionAnalysisBatchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analyses: list[SectionAnalysisOutput] = Field(
        description="Analysis results for each section in the batch."
    )
