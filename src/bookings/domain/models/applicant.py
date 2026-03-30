from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from bookings.domain.exceptions import ApplicantRiskTooHighError


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass(frozen=True)
class BookingApplicant:
    id: str
    external_id: str
    supabase_user_id: str | None
    organization_id: str
    name: str
    email: str
    risk_level: RiskLevel
    created_at: datetime

    @staticmethod
    def from_screening_event(data: dict[str, Any]) -> "BookingApplicant":
        risk_value = data.get("screening", {}).get("risk_level") or data.get("risk_level", "")
        risk = RiskLevel(risk_value)
        applicant_id = str(data.get("applicant_id", ""))
        if risk == RiskLevel.HIGH:
            raise ApplicantRiskTooHighError(applicant_id)

        from uuid import uuid4

        return BookingApplicant(
            id=str(uuid4()),
            external_id=applicant_id,
            supabase_user_id=None,
            organization_id=str(data.get("organization_id", "")),
            name=data.get("name", ""),
            email=data.get("email", ""),
            risk_level=risk,
            created_at=datetime.now(),
        )

    def is_approved(self) -> bool:
        return self.risk_level in (RiskLevel.LOW, RiskLevel.MEDIUM)
