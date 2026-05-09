from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from shared.jobs.domain.job import JobEntityType, JobKind, JobStatus


class JobResponse(BaseModel):
    id: UUID
    organization_id: UUID
    requested_by_user_id: UUID
    kind: JobKind
    status: JobStatus
    entity_type: JobEntityType
    entity_id: UUID
    title: str
    error_code: str | None
    error_message: str | None
    result_summary: dict[str, Any] | None
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
