from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID


class ApplicantStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class IncomeRecord:
    month: str  # "YYYY-MM"
    amount: float
    source: str


@dataclass
class Applicant:
    id: UUID
    property_id: str
    property_title: str
    visitor_name: str
    visitor_email: str
    agency_id: UUID
    status: ApplicantStatus
    created_at: datetime
    updated_at: datetime
    visitor_phone: str | None = None
    visitor_nif: str | None = None
    visitor_date_of_birth: date | None = None
    property_price: float | None = None
    property_address: str | None = None
    has_id_document: bool = False
    has_proof_of_income: bool = False
    justification: str | None = None
    message: str | None = None
    income_records: list[IncomeRecord] = field(default_factory=list)
    resolved_at: datetime | None = None
    form_request_id: UUID | None = None
    screening_applicant_id: UUID | None = None
