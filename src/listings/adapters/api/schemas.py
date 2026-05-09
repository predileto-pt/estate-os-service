from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from listings.domain.models import ListingType, Typology


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


class PropertyPriceResponse(BaseModel):
    id: UUID
    amount: Decimal
    listing_type: ListingType


class PropertyImageResponse(BaseModel):
    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    display_order: int
    download_url: str


class ListedPropertyResponse(BaseModel):
    """Public-facing listing payload.

    `address` removed (privacy fix, spec
    `2026-05-property-address-enrichment-fix`). Structured location
    fields (parish/municipality/district/country) are NOT exposed in v1
    — they live on `property_listings`, which the public route doesn't
    yet read. Exposing them is a follow-up that switches the public
    route from the legacy `ListedProperty` (over `properties`) to
    `PropertyListing` (over `property_listings`).
    """

    id: UUID
    organization_id: UUID
    listing_type: ListingType
    typology: Typology
    description: str | None
    characteristics: PropertyCharacteristicsResponse | None = None
    latitude: float | None = None
    longitude: float | None = None
    created_at: datetime
    updated_at: datetime
    prices: list[PropertyPriceResponse]
    images: list[PropertyImageResponse] = []


class PaginatedListingResponse(BaseModel):
    items: list[ListedPropertyResponse]
    total: int
    limit: int
    offset: int
