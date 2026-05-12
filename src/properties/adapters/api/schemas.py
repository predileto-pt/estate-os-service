from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from properties.domain.models.extraction_job import ExtractionJobStatus
from properties.domain.models.property import ListingType, PropertyStatus, Typology
from properties.domain.models.property_owner import CivilStatus, DocumentType
from properties.domain.models.property_poi import PoiCategory


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


# --- Property Summary ---


class PropertySummaryOwnerResponse(BaseModel):
    full_name: str


class PropertySummaryResponse(BaseModel):
    id: UUID
    address: str
    listing_type: ListingType
    typology: Typology
    price: Decimal | None
    owners: list[PropertySummaryOwnerResponse]


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


class UpdatePropertyOwnerContactRequest(BaseModel):
    email: str | None = None
    phone_number: str | None = None


class UpdatePropertyAddressRequest(BaseModel):
    address: str = Field(min_length=1, description="New street address; whitespace-only rejected")

    @field_validator("address")
    @classmethod
    def _strip_and_require_nonempty(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("address must not be empty")
        return cleaned


class UpdatePropertyTitleRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200, description="New title; whitespace-only rejected")

    @field_validator("title")
    @classmethod
    def _strip_and_require_nonempty(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("title must not be empty")
        return cleaned


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
    email: str | None = None
    phone_number: str | None = None
    email_verified: bool = False
    phone_verified: bool = False
    created_at: datetime
    updated_at: datetime


# --- Property Images ---


class PresignImageFileSpec(BaseModel):
    filename: str
    content_type: str = "image/jpeg"


class PresignImageRequest(BaseModel):
    organization_id: UUID
    property_id: UUID
    files: list[PresignImageFileSpec] = Field(min_length=1, max_length=20)


class PresignedImageFileResponse(BaseModel):
    image_id: UUID
    s3_key: str
    upload_url: str


class PresignImageResponse(BaseModel):
    files: list[PresignedImageFileResponse]


class RecordPropertyImageRequest(BaseModel):
    organization_id: UUID
    property_id: UUID
    image_id: UUID
    s3_key: str
    filename: str
    content_type: str
    size_bytes: int = Field(gt=0)


class ReorderPropertyImagesRequest(BaseModel):
    organization_id: UUID
    property_id: UUID
    image_ids: list[UUID] = Field(min_length=1)


class PropertyImageResponse(BaseModel):
    id: UUID
    property_id: UUID
    s3_key: str
    filename: str
    content_type: str
    size_bytes: int
    display_order: int
    download_url: str
    created_at: datetime
    updated_at: datetime


# --- Property ---


class CreatePropertyRequest(BaseModel):
    organization_id: UUID
    title: str = Field(min_length=1, max_length=200)
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
    title: str
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
    images: list[PropertyImageResponse] = []


class PublicPropertyResponse(BaseModel):
    id: UUID
    organization_id: UUID
    title: str
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
    prices: list[PropertyPriceResponse]
    images: list[PropertyImageResponse] = []


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
    # Link to the unified background_jobs row (ADR-012). Nullable for
    # rows created before the unified surface existed.
    tracked_job_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


# --- Property POI ---


class PropertyPoiBase(BaseModel):
    category: PoiCategory
    name: str = Field(min_length=1, max_length=200)
    distance_meters: float = Field(ge=0)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    place_type: str | None = None
    place_id: str | None = None
    metadata: dict = Field(default_factory=dict)
    # Place-details fields (spec 2026-05-poi-rich-metadata).
    # Manual create/update accepts these; auto-discovery (Phase 2)
    # writes them via update_place_details. No URL or schema validation
    # on `image_urls` / `reviews` in v1 — agent-mediated trust.
    address: str | None = None
    image_urls: list[str] = Field(default_factory=list, max_length=5)
    reviews: list[dict] | None = None


class CreatePropertyPoiRequest(PropertyPoiBase):
    """One POI inside a `ReplacePropertyPoisRequest.pois` list."""


class ReplacePropertyPoisRequest(BaseModel):
    pois: list[CreatePropertyPoiRequest] = Field(default_factory=list, max_length=200)


class UpdatePropertyPoiRequest(BaseModel):
    """All fields optional — PATCH semantics."""

    category: PoiCategory | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    distance_meters: float | None = Field(default=None, ge=0)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    place_type: str | None = None
    place_id: str | None = None
    metadata: dict | None = None
    # Place-details fields (spec 2026-05-poi-rich-metadata). Optional on
    # PATCH so manual edits can override Phase 2 results if needed.
    address: str | None = None
    image_urls: list[str] | None = Field(default=None, max_length=5)
    reviews: list[dict] | None = None


class PropertyPoiResponse(PropertyPoiBase):
    id: UUID
    property_id: UUID
    manually_edited: bool
    created_at: datetime
    updated_at: datetime


# --- Property POI auto-discovery (workflow trigger) ---


class EnrichPropertyRequest(BaseModel):
    force: bool = False


class EnrichPropertyResponse(BaseModel):
    job_id: UUID
    status: str = "processing"
    property_id: UUID
