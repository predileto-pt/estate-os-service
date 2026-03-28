from typing import Any
from uuid import UUID

from applicant_screening.domain.models import DomainEvent, EventType


def applicant_submitted(applicant_id: UUID, **payload: Any) -> DomainEvent:
    return DomainEvent(applicant_id=applicant_id, event_type=EventType.APPLICANT_SUBMITTED, payload=payload)


def documents_extracted(applicant_id: UUID, **payload: Any) -> DomainEvent:
    return DomainEvent(applicant_id=applicant_id, event_type=EventType.DOCUMENTS_EXTRACTED, payload=payload)


def applicant_screened(applicant_id: UUID, **payload: Any) -> DomainEvent:
    return DomainEvent(applicant_id=applicant_id, event_type=EventType.APPLICANT_SCREENED, payload=payload)
