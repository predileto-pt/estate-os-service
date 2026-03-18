from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from property_management.domain.models.extraction_job import ExtractionJobStatus
from property_management.domain.models.property import ListingType, PropertyStatus, Typology
from property_management.domain.models.property_owner import CivilStatus, DocumentType


# --- Property Price ---


class CreatePropertyPriceRequest(BaseModel):
    organization_id: UUID
    property_id: UUID
    amount: Decimal = Field(gt=0, description="Price amount in euros")
    listing_type: ListingType


class PropertyPriceResponse(BaseModel):
    id: UUID
    property_id: UUID
    amount: Decimal
    listing_type: ListingType
    created_at: datetime
    updated_at: datetime


# --- Property Owner ---


class CreatePropertyOwnerRequest(BaseModel):
    organization_id: UUID
    property_id: UUID
    full_name: str
    civil_status: CivilStatus
    address: str
    nif: str = Field(description="Tax identification number (NIF), 9 digits")
    document_type: DocumentType
    document_id: str
    issued_by: str = Field(description="Issuing authority")
    issuing_district: str | None = None
    date_of_birth: date


class PropertyOwnerResponse(BaseModel):
    id: UUID
    property_id: UUID
    full_name: str
    civil_status: CivilStatus | None
    address: str
    nif: str
    document_type: DocumentType | None
    document_id: str | None
    issued_by: str | None
    issuing_district: str | None
    date_of_birth: date | None
    created_at: datetime
    updated_at: datetime


# --- Property ---


class CreatePropertyRequest(BaseModel):
    organization_id: UUID
    address: str
    listing_type: ListingType
    typology: Typology
    description: str | None = None


class PropertyCharacteristicsResponse(BaseModel):
    area_in_m2: float | None = None
    num_of_bedrooms: int | None = None
    num_of_bathrooms: int | None = None
    built_at: int | None = None
    energy_rating: str | None = None
    floor: int | None = None
    parking_spaces: int | None = None
    has_elevator: bool | None = None
    has_garden: bool | None = None
    has_pool: bool | None = None


class PropertyResponse(BaseModel):
    id: UUID
    organization_id: UUID
    address: str
    listing_type: ListingType
    typology: Typology
    status: PropertyStatus
    description: str | None
    characteristics: PropertyCharacteristicsResponse | None = None
    latitude: float | None = None
    longitude: float | None = None
    created_at: datetime
    updated_at: datetime
    owners: list[PropertyOwnerResponse]
    prices: list[PropertyPriceResponse]


# --- Extraction Jobs ---


class PresignFileSpec(BaseModel):
    filename: str
    content_type: str = "application/pdf"


class PresignRequest(BaseModel):
    files: list[PresignFileSpec] = Field(min_length=1, max_length=5)


class PresignedFileResponse(BaseModel):
    s3_key: str
    upload_url: str


class PresignResponse(BaseModel):
    job_id: str
    files: list[PresignedFileResponse]


class SubmitExtractionRequest(BaseModel):
    job_id: str
    organization_id: UUID
    document_keys: list[str] = Field(min_length=1, max_length=5)
    listing_type: ListingType
    typology: Typology


class ExtractionJobResponse(BaseModel):
    id: UUID
    user_id: UUID
    organization_id: UUID
    status: ExtractionJobStatus
    document_keys: list[str]
    listing_type: str | None = None
    typology: str | None = None
    property_id: UUID | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
