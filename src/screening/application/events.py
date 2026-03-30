from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


class DocumentPayload(BaseModel):
    document_type: str  # ID_DOCUMENT / PROOF_OF_INCOME
    s3_key: str
    original_filename: str


class ScreeningResultPayload(BaseModel):
    risk_level: str  # LOW / MEDIUM / HIGH
    identity_verified: bool
    income_verified: bool
    dti_ratio: float
    justification: str
    average_monthly_income: float


class ApplicantScreenedEvent(BaseModel):
    event_type: str = "APPLICANT_SCREENED"
    # Identity
    applicant_id: UUID
    form_request_id: UUID
    organization_id: UUID
    name: str
    email: str
    date_of_birth: date
    # Property
    listing_type: str  # ARRENDAMENTO / VENDA
    property_type: str | None = None  # APARTAMENTO / MORADIA
    property_value: float | None = None
    monthly_rent: float | None = None
    # Documents
    has_id_document: bool
    has_proof_of_income: bool
    documents: list[DocumentPayload]
    # Screening
    screening: ScreeningResultPayload
    screened_at: datetime
