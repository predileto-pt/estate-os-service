from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from screening.domain.models.applicant import ListingType, PropertyType


class IntakeFormRequestStatus(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


@dataclass
class IntakeFormRequest:
    organization_id: UUID
    applicant_name: str
    applicant_email: str
    property_id: str
    listing_type: ListingType
    id: UUID = field(default_factory=uuid4)
    property_type: PropertyType | None = None
    applicant_phone: str | None = None
    property_title: str | None = None
    property_price: float | None = None
    property_address: str | None = None
    status: IntakeFormRequestStatus = IntakeFormRequestStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
