from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID, uuid4

from applicant_screening.domain.models.applicant import ListingType, PropertyType


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass
class ScreeningReport:
    applicant_id: UUID
    risk_level: RiskLevel
    identity_verified: bool
    income_verified: bool
    dti_ratio: float
    justification: str
    listing_type: ListingType
    average_monthly_income: float
    id: UUID = field(default_factory=uuid4)
    property_type: PropertyType | None = None
