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


class POIResponse(BaseModel):
    """POI matched against the user's extracted `nearby_pois`. Rich
    fields surface from the listings projection (populated by the
    properties POI snapshot — ADR-014 §13). Only the q-set search
    path populates these; q-empty calls leave `matched_pois` /
    `unmatched_pois` as empty lists."""

    category: str
    name: str
    distance_meters: float
    address: str | None = None
    image_urls: list[str] = []
    reviews: list[dict] | None = None


class ListedPropertyResponse(BaseModel):
    """Public-facing listing payload, served from the
    `property_listings` projection (collapsed from the legacy
    `ListedProperty` over the live `properties` table).

    `address` is intentionally NOT here (privacy fix, spec
    `2026-05-property-address-enrichment-fix`). Structured location
    fields (parish/municipality/district/country) ARE exposed now that
    the route reads from the projection.

    `matched_pois` / `unmatched_pois` (ADR-014 §15) default to `[]`
    — ALWAYS present, just empty on the q-empty path. Empty defaults
    keep the schema regular and don't require
    `response_model_exclude_none` (which would strip the nullable
    parish/municipality/district fields too — that's a v1
    contract break).
    """

    id: UUID
    organization_id: UUID
    title: str
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
    # Populated on the public detail endpoint (`GET /properties/{id}`)
    # with the listing's full POI set, sorted ascending by distance.
    # The list endpoints leave it `[]` — they expose POI signal only
    # through `matched_pois`/`unmatched_pois` on the q-set search path.
    pois: list[POIResponse] = []
    matched_pois: list[POIResponse] = []
    unmatched_pois: list[str] = []


class PaginatedListingResponse(BaseModel):
    """Offset/limit response shape — used by the admin endpoint
    `GET /api/v1/admin/listings/properties`. The public endpoint
    switched to `CursorPageResponse` in ADR-016."""

    items: list[ListedPropertyResponse]
    total: int
    limit: int
    offset: int


class CursorPageResponse(BaseModel):
    """Cursor-paginated response shape — used by the public endpoint
    `GET /api/v1/listings/properties`. `next_cursor` is an opaque
    token from `listings.domain.pagination.encode`; pass it back
    verbatim as `?cursor=` on the next request to fetch the next
    page. `null` means end of results."""

    items: list[ListedPropertyResponse]
    next_cursor: str | None
    limit: int


class MunicipalityNode(BaseModel):
    name: str
    parishes: list[str]


class DistrictNode(BaseModel):
    name: str
    municipalities: list[MunicipalityNode]


class CountryNode(BaseModel):
    code: str
    name: str
    districts: list[DistrictNode]


class LocationTreeResponse(BaseModel):
    """Response schema for `GET /api/v1/listings/locations`. Drives
    the FE selector (country → district → municipality → parish).

    Served from a bundled JSON catalog
    (`src/listings/static_data/locations.json`), NOT derived from
    `property_listings`. The full geography renders from day one;
    empty regions are still surfaced. Spec amended 2026-05-11."""

    countries: list[CountryNode]
