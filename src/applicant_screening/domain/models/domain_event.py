from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class EventType(StrEnum):
    APPLICANT_SUBMITTED = "APPLICANT_SUBMITTED"
    DOCUMENTS_EXTRACTED = "DOCUMENTS_EXTRACTED"
    APPLICANT_SCREENED = "APPLICANT_SCREENED"


@dataclass
class DomainEvent:
    applicant_id: UUID
    event_type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: UUID = field(default_factory=uuid4)
