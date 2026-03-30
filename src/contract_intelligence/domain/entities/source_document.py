from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from contract_intelligence.domain.exceptions import InvalidStatusTransitionError

if TYPE_CHECKING:
    from contract_intelligence.application.ports.reducto import ExtractedField, ParsedSection


class UploadStatus(StrEnum):
    UPLOADED = "uploaded"
    PARSED = "parsed"
    EXTRACTED = "extracted"
    ANALYZED = "analyzed"
    FAILED = "failed"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    CORRECTED = "corrected"
    REJECTED = "rejected"
    MERGED = "merged"
    SPLIT = "split"


_UPLOAD_TRANSITIONS: dict[UploadStatus, set[UploadStatus]] = {
    UploadStatus.UPLOADED: {UploadStatus.PARSED, UploadStatus.EXTRACTED, UploadStatus.FAILED},
    UploadStatus.PARSED: {UploadStatus.EXTRACTED, UploadStatus.FAILED},
    UploadStatus.EXTRACTED: {UploadStatus.ANALYZED, UploadStatus.FAILED},
    UploadStatus.ANALYZED: {UploadStatus.FAILED},
    UploadStatus.FAILED: set(),
}

_RUN_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.PENDING: {RunStatus.RUNNING},
    RunStatus.RUNNING: {RunStatus.SUCCEEDED, RunStatus.FAILED},
    RunStatus.SUCCEEDED: set(),
    RunStatus.FAILED: set(),
}

_REVIEW_TRANSITIONS: dict[ReviewStatus, set[ReviewStatus]] = {
    ReviewStatus.PENDING: {
        ReviewStatus.ACCEPTED,
        ReviewStatus.CORRECTED,
        ReviewStatus.REJECTED,
        ReviewStatus.MERGED,
        ReviewStatus.SPLIT,
    },
    ReviewStatus.ACCEPTED: set(),
    ReviewStatus.CORRECTED: set(),
    ReviewStatus.REJECTED: set(),
    ReviewStatus.MERGED: set(),
    ReviewStatus.SPLIT: set(),
}


def _validate_transition(current: Any, target: Any, transitions: dict, entity_name: str) -> None:
    allowed = transitions.get(current, set())
    if target not in allowed:
        raise InvalidStatusTransitionError(
            f"{entity_name} cannot transition from {current} to {target}"
        )


class SectionType(StrEnum):
    STATIC = "static"
    PARAMETERIZED = "parameterized"
    CONDITIONAL = "conditional"
    GENERATIVE = "generative"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RecommendedStrategy(StrEnum):
    LITERAL = "literal"
    TEMPLATE = "template"
    TEMPLATE_VARIANT = "template_variant"
    AI_DRAFT = "ai_draft"


class AnalysisReferenceType(StrEnum):
    FIELD = "field"
    CONDITION = "condition"


@dataclass
class SourceSectionAnalysisReference:
    source_section_analysis_id: UUID
    reference_type: AnalysisReferenceType
    reference_key: str
    id: UUID = field(default_factory=uuid4)
    display_label: str | None = None
    confidence: Decimal | None = None
    created_at: datetime | None = None


@dataclass
class SourceSectionAnalysis:
    source_section_analysis_run_id: UUID
    source_section_id: UUID
    section_type: SectionType
    reasoning: str
    risk_level: RiskLevel
    recommended_strategy: RecommendedStrategy
    id: UUID = field(default_factory=uuid4)
    review_status: ReviewStatus = ReviewStatus.PENDING
    review_notes: str | None = None
    corrected_section_type: SectionType | None = None
    corrected_risk_level: RiskLevel | None = None
    corrected_strategy: RecommendedStrategy | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    references: list[SourceSectionAnalysisReference] = field(default_factory=list)

    def accept(self) -> None:
        _validate_transition(
            self.review_status, ReviewStatus.ACCEPTED, _REVIEW_TRANSITIONS, "SourceSectionAnalysis"
        )
        self.review_status = ReviewStatus.ACCEPTED

    def reject(self) -> None:
        _validate_transition(
            self.review_status, ReviewStatus.REJECTED, _REVIEW_TRANSITIONS, "SourceSectionAnalysis"
        )
        self.review_status = ReviewStatus.REJECTED

    def correct(
        self,
        *,
        section_type: SectionType | None = None,
        risk_level: RiskLevel | None = None,
        strategy: RecommendedStrategy | None = None,
        review_notes: str | None = None,
    ) -> None:
        _validate_transition(
            self.review_status, ReviewStatus.CORRECTED, _REVIEW_TRANSITIONS, "SourceSectionAnalysis"
        )
        self.review_status = ReviewStatus.CORRECTED
        if section_type is not None:
            self.corrected_section_type = section_type
        if risk_level is not None:
            self.corrected_risk_level = risk_level
        if strategy is not None:
            self.corrected_strategy = strategy
        if review_notes is not None:
            self.review_notes = review_notes


@dataclass
class SourceSectionAnalysisRun:
    source_document_id: UUID
    id: UUID = field(default_factory=uuid4)
    provider: str = "openai"
    model_name: str = "gpt-5.4"
    prompt_version: str = "v1"
    status: RunStatus = RunStatus.PENDING
    created_at: datetime | None = None
    completed_at: datetime | None = None
    analyses: list[SourceSectionAnalysis] = field(default_factory=list)

    def mark_running(self) -> None:
        _validate_transition(
            self.status, RunStatus.RUNNING, _RUN_TRANSITIONS, "SourceSectionAnalysisRun"
        )
        self.status = RunStatus.RUNNING

    def mark_succeeded(self, completed_at: datetime) -> None:
        _validate_transition(
            self.status, RunStatus.SUCCEEDED, _RUN_TRANSITIONS, "SourceSectionAnalysisRun"
        )
        self.status = RunStatus.SUCCEEDED
        self.completed_at = completed_at

    def mark_failed(self, completed_at: datetime) -> None:
        _validate_transition(
            self.status, RunStatus.FAILED, _RUN_TRANSITIONS, "SourceSectionAnalysisRun"
        )
        self.status = RunStatus.FAILED
        self.completed_at = completed_at


@dataclass
class SourceFieldEvidence:
    source_extraction_run_id: UUID
    field_key: str
    id: UUID = field(default_factory=uuid4)
    source_section_id: UUID | None = None
    field_value_json: Any = None
    source_text: str | None = None
    page_number: int | None = None
    confidence: Decimal | None = None
    review_status: ReviewStatus = ReviewStatus.PENDING
    corrected_value_json: Any = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def accept(self) -> None:
        _validate_transition(
            self.review_status, ReviewStatus.ACCEPTED, _REVIEW_TRANSITIONS, "SourceFieldEvidence"
        )
        self.review_status = ReviewStatus.ACCEPTED

    def reject(self) -> None:
        _validate_transition(
            self.review_status, ReviewStatus.REJECTED, _REVIEW_TRANSITIONS, "SourceFieldEvidence"
        )
        self.review_status = ReviewStatus.REJECTED

    def correct(self, *, corrected_value_json: Any) -> None:
        _validate_transition(
            self.review_status, ReviewStatus.CORRECTED, _REVIEW_TRANSITIONS, "SourceFieldEvidence"
        )
        self.review_status = ReviewStatus.CORRECTED
        self.corrected_value_json = corrected_value_json

    @classmethod
    def from_extracted(
        cls, extraction_run_id: UUID, extracted_field: ExtractedField
    ) -> SourceFieldEvidence:
        return cls(
            source_extraction_run_id=extraction_run_id,
            field_key=extracted_field.field_key,
            field_value_json=extracted_field.field_value,
            source_text=extracted_field.source_text,
            page_number=extracted_field.page_number,
            confidence=(
                Decimal(str(extracted_field.confidence))
                if extracted_field.confidence is not None
                else None
            ),
        )


@dataclass
class SourceParseRun:
    source_document_id: UUID
    id: UUID = field(default_factory=uuid4)
    provider: str = "reducto"
    provider_job_id: str | None = None
    parse_config_json: dict = field(default_factory=dict)
    response_json: dict | None = None
    status: RunStatus = RunStatus.PENDING
    created_at: datetime | None = None
    completed_at: datetime | None = None

    @classmethod
    def start(cls, source_document_id: UUID) -> SourceParseRun:
        run = cls(source_document_id=source_document_id)
        run.mark_running()
        return run

    def mark_running(self) -> None:
        _validate_transition(self.status, RunStatus.RUNNING, _RUN_TRANSITIONS, "SourceParseRun")
        self.status = RunStatus.RUNNING

    def mark_succeeded(
        self,
        completed_at: datetime,
        provider_job_id: str | None = None,
        response_json: dict | None = None,
    ) -> None:
        _validate_transition(self.status, RunStatus.SUCCEEDED, _RUN_TRANSITIONS, "SourceParseRun")
        self.status = RunStatus.SUCCEEDED
        self.completed_at = completed_at
        if provider_job_id is not None:
            self.provider_job_id = provider_job_id
        if response_json is not None:
            self.response_json = response_json

    def mark_failed(self, completed_at: datetime) -> None:
        _validate_transition(self.status, RunStatus.FAILED, _RUN_TRANSITIONS, "SourceParseRun")
        self.status = RunStatus.FAILED
        self.completed_at = completed_at


@dataclass
class SourceSection:
    source_document_id: UUID
    sort_order: int
    id: UUID = field(default_factory=uuid4)
    section_key: str | None = None
    title: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    extracted_text: str | None = None
    normalized_text: str | None = None
    classification_confidence: Decimal | None = None
    review_status: ReviewStatus = ReviewStatus.PENDING
    created_at: datetime | None = None
    updated_at: datetime | None = None
    field_evidence: list[SourceFieldEvidence] = field(default_factory=list)
    analyses: list[SourceSectionAnalysis] = field(default_factory=list)

    def accept(self) -> None:
        _validate_transition(
            self.review_status, ReviewStatus.ACCEPTED, _REVIEW_TRANSITIONS, "SourceSection"
        )
        self.review_status = ReviewStatus.ACCEPTED

    def reject(self) -> None:
        _validate_transition(
            self.review_status, ReviewStatus.REJECTED, _REVIEW_TRANSITIONS, "SourceSection"
        )
        self.review_status = ReviewStatus.REJECTED

    def correct(self, *, normalized_text: str | None = None) -> None:
        _validate_transition(
            self.review_status, ReviewStatus.CORRECTED, _REVIEW_TRANSITIONS, "SourceSection"
        )
        self.review_status = ReviewStatus.CORRECTED
        if normalized_text is not None:
            self.normalized_text = normalized_text

    @classmethod
    def from_parsed(cls, source_document_id: UUID, parsed_section: ParsedSection) -> SourceSection:
        return cls(
            source_document_id=source_document_id,
            sort_order=parsed_section.sort_order,
            title=parsed_section.title,
            page_start=parsed_section.page_start,
            page_end=parsed_section.page_end,
            extracted_text=parsed_section.content,
        )


@dataclass
class SourceExtractionRun:
    source_document_id: UUID
    schema_version: str
    extraction_schema_json: dict
    id: UUID = field(default_factory=uuid4)
    provider: str = "reducto"
    provider_job_id: str | None = None
    result_json: dict | None = None
    status: RunStatus = RunStatus.PENDING
    created_at: datetime | None = None
    completed_at: datetime | None = None
    field_evidence: list[SourceFieldEvidence] = field(default_factory=list)

    @classmethod
    def create_succeeded(
        cls,
        source_document_id: UUID,
        schema_version: str,
        extraction_schema_json: dict,
        completed_at: datetime,
        *,
        provider_job_id: str | None = None,
        result_json: dict | None = None,
    ) -> SourceExtractionRun:
        return cls(
            source_document_id=source_document_id,
            schema_version=schema_version,
            extraction_schema_json=extraction_schema_json,
            provider_job_id=provider_job_id,
            result_json=result_json,
            status=RunStatus.SUCCEEDED,
            completed_at=completed_at,
        )

    def mark_succeeded(
        self,
        completed_at: datetime,
        provider_job_id: str | None = None,
        result_json: dict | None = None,
    ) -> None:
        _validate_transition(
            self.status, RunStatus.SUCCEEDED, _RUN_TRANSITIONS, "SourceExtractionRun"
        )
        self.status = RunStatus.SUCCEEDED
        self.completed_at = completed_at
        if provider_job_id is not None:
            self.provider_job_id = provider_job_id
        if result_json is not None:
            self.result_json = result_json

    def mark_failed(self, completed_at: datetime) -> None:
        _validate_transition(self.status, RunStatus.FAILED, _RUN_TRANSITIONS, "SourceExtractionRun")
        self.status = RunStatus.FAILED
        self.completed_at = completed_at


@dataclass
class SourceDocument:
    filename: str
    storage_url: str
    mime_type: str
    document_hash: str
    id: UUID = field(default_factory=uuid4)
    organization_id: UUID | None = None
    page_count: int | None = None
    language_code: str | None = None
    upload_status: UploadStatus = UploadStatus.UPLOADED
    created_at: datetime | None = None
    parse_runs: list[SourceParseRun] = field(default_factory=list)
    sections: list[SourceSection] = field(default_factory=list)
    extraction_runs: list[SourceExtractionRun] = field(default_factory=list)
    analysis_runs: list[SourceSectionAnalysisRun] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        filename: str,
        storage_url: str,
        mime_type: str,
        document_hash: str,
        *,
        id: UUID | None = None,
        organization_id: UUID | None = None,
    ) -> SourceDocument:
        return cls(
            filename=filename,
            storage_url=storage_url,
            mime_type=mime_type,
            document_hash=document_hash,
            id=id or uuid4(),
            organization_id=organization_id,
            upload_status=UploadStatus.UPLOADED,
        )

    def mark_parsed(self) -> None:
        _validate_transition(
            self.upload_status, UploadStatus.PARSED, _UPLOAD_TRANSITIONS, "SourceDocument"
        )
        self.upload_status = UploadStatus.PARSED

    def mark_extracted(self) -> None:
        _validate_transition(
            self.upload_status, UploadStatus.EXTRACTED, _UPLOAD_TRANSITIONS, "SourceDocument"
        )
        self.upload_status = UploadStatus.EXTRACTED

    def mark_analyzed(self) -> None:
        _validate_transition(
            self.upload_status, UploadStatus.ANALYZED, _UPLOAD_TRANSITIONS, "SourceDocument"
        )
        self.upload_status = UploadStatus.ANALYZED

    def mark_failed(self) -> None:
        _validate_transition(
            self.upload_status, UploadStatus.FAILED, _UPLOAD_TRANSITIONS, "SourceDocument"
        )
        self.upload_status = UploadStatus.FAILED

    def record_page_count(self, count: int) -> None:
        self.page_count = count

    @property
    def contract_name(self) -> str | None:
        for run in self.extraction_runs:
            for fe in run.field_evidence:
                if fe.field_key == "contract_type":
                    val = fe.field_value_json
                    if isinstance(val, dict) and "value" in val:
                        return val["value"]
                    return val
        return None

    @property
    def latest_succeeded_parse_run(self) -> SourceParseRun | None:
        succeeded = [r for r in self.parse_runs if r.status == RunStatus.SUCCEEDED]
        if not succeeded:
            return None
        return max(succeeded, key=lambda r: r.completed_at or r.created_at)
