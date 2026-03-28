from datetime import date
from uuid import UUID

from pydantic import BaseModel, field_validator

from applicant_screening.domain.models import DocumentType, ListingType, PropertyType, RiskLevel


class CreateApplicantRequest(BaseModel):
    nif: str
    name: str
    date_of_birth: date
    email: str
    organization_id: UUID
    form_request_id: UUID
    listing_type: ListingType
    property_type: PropertyType
    phone: str | None = None
    property_value: float | None = None
    monthly_rent: float | None = None
    property_title: str = "n/a"
    property_address: str = "n/a"

    @field_validator("nif")
    @classmethod
    def validate_nif(cls, v: str) -> str:
        digits = v.strip()
        if len(digits) != 9 or not digits.isdigit():
            raise ValueError("NIF must be exactly 9 digits")
        return digits


class SubmissionResponse(BaseModel):
    applicant_id: UUID
    documents_uploaded: int
    message: str


# --- Presigned upload models ---


class FileUploadSpec(BaseModel):
    filename: str
    content_type: str
    document_type: DocumentType


class PresignedUploadRequest(BaseModel):
    form_request_id: UUID
    files: list[FileUploadSpec]


class PresignedFileUpload(BaseModel):
    filename: str
    s3_key: str
    upload_url: str
    document_type: DocumentType


class PresignedUploadResponse(BaseModel):
    upload_id: str
    files: list[PresignedFileUpload]


class UploadedDocumentSpec(BaseModel):
    s3_key: str
    filename: str
    content_type: str
    document_type: DocumentType


class CreateSubmissionRequest(BaseModel):
    nif: str
    name: str
    date_of_birth: date
    email: str
    organization_id: UUID
    form_request_id: UUID
    listing_type: ListingType
    property_type: PropertyType
    terms_accepted: bool
    documents: list[UploadedDocumentSpec]
    phone: str | None = None
    property_value: float | None = None
    monthly_rent: float | None = None
    property_title: str = "n/a"
    property_address: str = "n/a"

    @field_validator("nif")
    @classmethod
    def validate_nif(cls, v: str) -> str:
        digits = v.strip()
        if len(digits) != 9 or not digits.isdigit():
            raise ValueError("NIF must be exactly 9 digits")
        return digits


class ScreeningReportResponse(BaseModel):
    applicant_id: UUID
    risk_level: RiskLevel
    identity_verified: bool
    income_verified: bool
    dti_ratio: float
    justification: str
    listing_type: ListingType
    property_type: PropertyType | None = None
    average_monthly_income: float


class ScreeningStatusResponse(BaseModel):
    applicant_id: UUID
    status: str
    report: ScreeningReportResponse | None = None


# LLM structured output models


class IdentityVerificationResult(BaseModel):
    identity_verified: bool
    nif_match: bool
    name_match: bool
    reasoning: str


class IncomeVerificationResult(BaseModel):
    income_verified: bool
    months_verified: int
    average_monthly_income: float
    same_name: bool
    reasoning: str


class AffordabilityResult(BaseModel):
    dti_ratio: float
    monthly_obligation: float
    is_affordable: bool
    reasoning: str


class ScreeningAssessmentResult(BaseModel):
    risk_level: RiskLevel
    identity_verified: bool
    income_verified: bool
    dti_ratio: float
    average_monthly_income: float
    justification: str


# ID document classification & extraction models


class IdClassificationResult(BaseModel):
    document_type: str
    confidence: float
    reasoning: str


class TituloResidenciaExtraction(BaseModel):
    full_name: str | None = None
    birth_date: str | None = None
    expiry_date: str | None = None
    tax_id_number: str | None = None
    warnings: list[str] = []
    confidence_scores: dict[str, float] = {}
    document_type_match: bool = True


class CartaoCidadaoExtraction(BaseModel):
    full_name: str | None = None
    birth_date: str | None = None
    expiry_date: str | None = None
    document_number: str | None = None
    warnings: list[str] = []
    confidence_scores: dict[str, float] = {}
    document_type_match: bool = True


class PassaporteExtraction(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    passport_number: str | None = None
    issue_date: str | None = None
    expiry_date: str | None = None
    warnings: list[str] = []
    confidence_scores: dict[str, float] = {}
    document_type_match: bool = True
