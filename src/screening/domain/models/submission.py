from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4


class SubmissionStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


@dataclass
class Submission:
    form_request_id: UUID
    organization_id: UUID
    id: UUID = field(default_factory=uuid4)
    applicant_id: UUID | None = None
    terms_accepted: bool = False
    status: SubmissionStatus = SubmissionStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
