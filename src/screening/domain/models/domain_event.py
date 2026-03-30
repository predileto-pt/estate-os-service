from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class EventType(StrEnum):
    APPLICANT_SUBMITTED = "APPLICANT_SUBMITTED"
    DOCUMENTS_EXTRACTED = "DOCUMENTS_EXTRACTED"
    APPLICANT_SCREENED = "APPLICANT_SCREENED"


@dataclass(frozen=True)
class DomainEvent:
    applicant_id: UUID
    event_type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True)
class ApplicantSubmitted(DomainEvent):
    event_type: EventType = field(default=EventType.APPLICANT_SUBMITTED, init=False)
    document_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", {"document_count": self.document_count})


@dataclass(frozen=True)
class DocumentsExtracted(DomainEvent):
    event_type: EventType = field(default=EventType.DOCUMENTS_EXTRACTED, init=False)
    document_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", {"document_count": self.document_count})


@dataclass(frozen=True)
class ApplicantScreened(DomainEvent):
    event_type: EventType = field(default=EventType.APPLICANT_SCREENED, init=False)
    risk_level: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", {"risk_level": self.risk_level})
