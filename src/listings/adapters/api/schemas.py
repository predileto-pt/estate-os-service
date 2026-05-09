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
    """Lean public price shape — no `id` since the public surface has
    no per-price actions (no detail page per price, no edit/delete).
    Trimmed during the legacy `ListingRepository` collapse into
    `PropertyListingRepository`."""

    amount: Decimal
    listing_type: ListingType


class PropertyImageResponse(BaseModel):
    """Lean public image shape: id (for keying), display_order,
    download_url. Trimmed `filename` / `content_type` / `size_bytes`
    during the projection-shape unification — none of those are
    necessary for rendering the gallery."""

    id: UUID
    display_order: int
    download_url: str


class ListedPropertyResponse(BaseModel):
    """Public-facing listing payload, served from the
    `property_listings` projection (collapsed from the legacy
    `ListedProperty` over the live `properties` table).

    `address` is intentionally NOT here (privacy fix, spec
    `2026-05-property-address-enrichment-fix`). Structured location
    fields (parish/municipality/district/country) ARE exposed now that
    the route reads from the projection.
    """

    id: UUID
    organization_id: UUID
    listing_type: ListingType
    typology: Typology
    description: str | None
    characteristics: PropertyCharacteristicsResponse | None = None
    parish: str | None = None
    municipality: str | None = None
    district: str | None = None
    country: str = "Portugal"
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
