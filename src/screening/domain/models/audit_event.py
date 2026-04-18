"""Screening-internal audit-log events.

These are NOT the cross-context `DomainEvent` at `src/shared/events/base.py`.
They're a separate concern: events that get **persisted** (via
`EventRepository.save`) as screening's own audit trail. Each record includes
the `applicant_id`, the `event_type` (a local `EventType` enum), a free-form
`payload`, and an `id`/`created_at` for ordering.

Cross-context broadcast — the thing the bookings/customers workers subscribe
to — uses `shared.events.base.DomainEvent` with event_type
`APPLICANT_SCREENED.v1`. The two concepts sit side by side without
colliding; this module owns the audit-log schema, the shared module owns
the envelope for inter-context messaging.
"""

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
class ScreeningAuditEvent:
    applicant_id: UUID
    event_type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True)
class ApplicantSubmitted(ScreeningAuditEvent):
    event_type: EventType = field(default=EventType.APPLICANT_SUBMITTED, init=False)
    document_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", {"document_count": self.document_count})


@dataclass(frozen=True)
class DocumentsExtracted(ScreeningAuditEvent):
    event_type: EventType = field(default=EventType.DOCUMENTS_EXTRACTED, init=False)
    document_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", {"document_count": self.document_count})


@dataclass(frozen=True)
class ApplicantScreened(ScreeningAuditEvent):
    event_type: EventType = field(default=EventType.APPLICANT_SCREENED, init=False)
    risk_level: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", {"risk_level": self.risk_level})
