from decimal import Decimal
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from identity.domain.models.user import User
from listings.adapters.api.schemas import (
    ListedPropertyResponse,
    PaginatedListingResponse,
    PropertyCharacteristicsResponse,
    PropertyImageResponse,
    PropertyPriceResponse,
)
from listings.domain.exceptions import PropertyNotFoundError
from listings.domain.models import ListingType, Typology
from listings.domain.property_filters import PropertyFilters
from listings.domain.property_listing import PropertyListing
from organizations.domain.models.membership import Membership
from shared.api.dependencies import require_org_member

logger = structlog.get_logger()

router = APIRouter(tags=["property-listings"])
admin_router = APIRouter(tags=["property-listings-admin"])


async def _generate_image_urls(request: Request, prop: PropertyListing) -> dict[str, str]:
    document_storage = getattr(request.app.state, "_listing_document_storage", None)
    if not document_storage or not prop.images:
        return {}
    urls = {}
    for image in prop.images:
        urls[str(image.id)] = await document_storage.get_download_url(image.s3_key)
    return urls


def _to_response(prop: PropertyListing, image_urls: dict[str, str]) -> ListedPropertyResponse:
    """Map the projection row to the public response.

    `address` intentionally absent (privacy fix). Structured location
    fields (parish/municipality/district/country) are now exposed from
    the projection. Characteristics are flattened into a response sub-
    object — `PropertyListing` carries them as flat columns rather
    than a nested `PropertyCharacteristics` object.
    """
    # Build the characteristics block only if any field is populated.
    char_fields = {
        "area_in_m2": prop.area_in_m2,
        "num_of_bedrooms": prop.num_of_bedrooms,
        "num_of_bathrooms": prop.num_of_bathrooms,
        "built_at": prop.built_at,
        "energy_rating": prop.energy_rating,
        "floor": prop.floor,
        "parking_spaces": prop.parking_spaces,
        "has_elevator": prop.has_elevator,
        "has_garden": prop.has_garden,
        "has_pool": prop.has_pool,
    }
    characteristics = (
        PropertyCharacteristicsResponse(**char_fields)
        if any(v is not None for v in char_fields.values())
        else None
    )

    return ListedPropertyResponse(
        id=prop.id,
        organization_id=prop.organization_id,
        listing_type=prop.listing_type,
        typology=prop.typology,
        description=prop.description,
        characteristics=characteristics,
        parish=prop.parish,
        municipality=prop.municipality,
        district=prop.district,
        country=prop.country,
        latitude=prop.latitude,
        longitude=prop.longitude,
        created_at=prop.created_at,
        updated_at=prop.updated_at,
        prices=[
            PropertyPriceResponse(amount=p.amount, listing_type=p.listing_type) for p in prop.prices
        ],
        images=[
            PropertyImageResponse(
                id=img.id,
                display_order=img.display_order,
                download_url=image_urls.get(str(img.id), ""),
            )
            for img in prop.images
        ],
    )


@router.get(
    "/properties",
    response_model=PaginatedListingResponse,
    summary="List active properties with filters",
)
async def list_properties(
    request: Request,
    listing_type: ListingType | None = Query(
        None, description="Filter by listing type (sale/purchase)"
    ),
    typology: Typology | None = Query(
        None, description="Filter by typology (house/apartment/land/ruin)"
    ),
    min_price: Decimal | None = Query(None, ge=0, description="Minimum price filter"),
    max_price: Decimal | None = Query(None, ge=0, description="Maximum price filter"),
    district: str | None = Query(
        None, description="Filter by district/location (partial match on address)"
    ),
    limit: int = Query(20, ge=1, le=100, description="Number of results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> PaginatedListingResponse:
    container = request.app.state.listing_container
    filters = PropertyFilters(
        listing_type=listing_type,
        typology=typology,
        min_price=min_price,
        max_price=max_price,
        district=district,
        limit=limit,
        offset=offset,
    )

    properties, total = await container.list_properties.execute(filters)

    items = []
    for prop in properties:
        image_urls = await _generate_image_urls(request, prop)
        items.append(_to_response(prop, image_urls))

    return PaginatedListingResponse(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/properties/{property_id}",
    response_model=ListedPropertyResponse,
    summary="Get a single active property by ID",
)
async def get_property(property_id: UUID, request: Request) -> ListedPropertyResponse:
    container = request.app.state.listing_container
    try:
        prop = await container.get_property.execute(property_id)
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")

    image_urls = await _generate_image_urls(request, prop)
    return _to_response(prop, image_urls)


# ── Admin (auth-gated, org-scoped) ───────────────────────────────────────────


@admin_router.get(
    "/properties",
    response_model=PaginatedListingResponse,
    summary="List active listings for the caller's organization (admin view)",
    responses={
        200: {"description": "Active listings for the organization"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not a member of this organization"},
    },
)
async def list_org_active_listings(
    organization_id: UUID,
    request: Request,
    listing_type: ListingType | None = Query(
        None, description="Filter by listing type (sale/purchase)"
    ),
    typology: Typology | None = Query(
        None, description="Filter by typology (house/apartment/land/ruin)"
    ),
    min_price: Decimal | None = Query(None, ge=0, description="Minimum price filter"),
    max_price: Decimal | None = Query(None, ge=0, description="Maximum price filter"),
    district: str | None = Query(
        None, description="Filter by district/location (partial match on address)"
    ),
    limit: int = Query(20, ge=1, le=100, description="Number of results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    _member: tuple[User, Membership] = Depends(require_org_member),
) -> PaginatedListingResponse:
    container = request.app.state.listing_container
    filters = PropertyFilters(
        listing_type=listing_type,
        typology=typology,
        min_price=min_price,
        max_price=max_price,
        district=district,
        limit=limit,
        offset=offset,
    )
    properties, total = await container.list_org_active_listings.execute(
        organization_id=organization_id,
        filters=filters,
    )

    items = []
    for prop in properties:
        image_urls = await _generate_image_urls(request, prop)
        items.append(_to_response(prop, image_urls))

    return PaginatedListingResponse(items=items, total=total, limit=limit, offset=offset)
