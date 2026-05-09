from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from shared.jobs.domain.exceptions import InvalidJobTransitionError


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobKind(str, enum.Enum):
    PROPERTY_DOCUMENT_EXTRACTION = "property_document_extraction"
    PROPERTY_ENRICHMENT = "property_enrichment"
    APPLICANT_SCREENING = "applicant_screening"
    CONTRACT_INGESTION = "contract_ingestion"
    CONTRACT_ANALYSIS = "contract_analysis"
    MEDIA_GENERATION_IMAGE = "media_generation_image"
    MEDIA_GENERATION_VIDEO = "media_generation_video"


class JobEntityType(str, enum.Enum):
    PROPERTY = "property"
    LISTING = "listing"
    APPLICANT = "applicant"
    CONTRACT = "contract"
    GENERATED_MEDIA = "generated_media"


_TERMINAL_STATUSES = frozenset({JobStatus.COMPLETED, JobStatus.FAILED})


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Job:
    id: UUID
    organization_id: UUID
    requested_by_user_id: UUID
    kind: JobKind
    entity_type: JobEntityType
    entity_id: UUID
    title: str
    status: JobStatus = JobStatus.PROCESSING
    error_code: str | None = None
    error_message: str | None = None
    result_summary: dict[str, Any] | None = None
    started_at: datetime = field(default_factory=_now)
    completed_at: datetime | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def mark_completed(self, result_summary: dict[str, Any] | None = None) -> None:
        if self.status == JobStatus.FAILED:
            raise InvalidJobTransitionError(f"Cannot complete job {self.id}: already FAILED")
        if self.status == JobStatus.COMPLETED:
            return
        self.status = JobStatus.COMPLETED
        self.result_summary = result_summary
        now = _now()
        self.completed_at = now
        self.updated_at = now

    def mark_failed(self, error_code: str, error_message: str) -> None:
        if self.status == JobStatus.COMPLETED:
            raise InvalidJobTransitionError(f"Cannot fail job {self.id}: already COMPLETED")
        if self.status == JobStatus.FAILED:
            return
        self.status = JobStatus.FAILED
        self.error_code = error_code
        self.error_message = error_message
        now = _now()
        self.completed_at = now
        self.updated_at = now

    def update_entity_id(self, entity_id: UUID) -> None:
        """Repoint a non-terminal row at a different entity. Used by the
        extraction workflow when the new property id becomes known."""
        if self.status in _TERMINAL_STATUSES:
            raise InvalidJobTransitionError(f"Cannot repoint job {self.id} after termination")
        self.entity_id = entity_id
        self.updated_at = _now()
