from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class BookingStatus(StrEnum):
    CONFIRMED = "confirmed"
    CANCELLED_BY_APPLICANT = "cancelled_by_applicant"
    CANCELLED_BY_AGENT = "cancelled_by_agent"


@dataclass(frozen=True)
class Booking:
    id: str
    slot_id: str
    applicant_id: str
    property_id: str
    organization_id: str
    status: BookingStatus
    notes: str
    created_at: datetime
    updated_at: datetime

    def is_confirmed(self) -> bool:
        return self.status == BookingStatus.CONFIRMED

    def belongs_to_applicant(self, applicant_id: str) -> bool:
        return self.applicant_id == applicant_id

    def belongs_to_organization(self, org_id: str) -> bool:
        return self.organization_id == org_id
