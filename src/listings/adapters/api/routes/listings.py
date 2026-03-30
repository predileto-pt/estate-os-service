from decimal import Decimal
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query, Request

from listings.adapters.api.schemas import (
    ListedPropertyResponse,
    PaginatedListingResponse,
    PropertyCharacteristicsResponse,
    PropertyImageResponse,
    PropertyPriceResponse,
)
from listings.application.ports.listing_repository import PropertyFilters
from listings.domain.exceptions import PropertyNotFoundError
from listings.domain.models import ListedProperty, ListingType, Typology

logger = structlog.get_logger()

router = APIRouter(tags=["property-listings"])


async def _generate_image_urls(request: Request, prop: ListedProperty) -> dict[str, str]:
    document_storage = getattr(request.app.state, "_listing_document_storage", None)
    if not document_storage or not prop.images:
        return {}
    urls = {}
    for image in prop.images:
        urls[str(image.id)] = await document_storage.get_download_url(image.s3_key)
    return urls


def _to_response(prop: ListedProperty, image_urls: dict[str, str]) -> ListedPropertyResponse:
    return ListedPropertyResponse(
        id=prop.id,
        organization_id=prop.organization_id,
        address=prop.address,
        listing_type=prop.listing_type,
        typology=prop.typology,
        description=prop.description,
        characteristics=(
            PropertyCharacteristicsResponse(
                area_in_m2=prop.characteristics.area_in_m2,
                num_of_bedrooms=prop.characteristics.num_of_bedrooms,
                num_of_bathrooms=prop.characteristics.num_of_bathrooms,
                built_at=prop.characteristics.built_at,
                energy_rating=prop.characteristics.energy_rating,
                floor=prop.characteristics.floor,
                parking_spaces=prop.characteristics.parking_spaces,
                has_elevator=prop.characteristics.has_elevator,
                has_garden=prop.characteristics.has_garden,
                has_pool=prop.characteristics.has_pool,
            )
            if prop.characteristics
            else None
        ),
        latitude=prop.latitude,
        longitude=prop.longitude,
        created_at=prop.created_at,
        updated_at=prop.updated_at,
        prices=[
            PropertyPriceResponse(
                id=p.id,
                amount=p.amount,
                listing_type=p.listing_type,
            )
            for p in prop.prices
        ],
        images=[
            PropertyImageResponse(
                id=img.id,
                filename=img.filename,
                content_type=img.content_type,
                size_bytes=img.size_bytes,
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
    listing_type: ListingType | None = Query(None, description="Filter by listing type (sale/purchase)"),
    typology: Typology | None = Query(None, description="Filter by typology (house/apartment/land/ruin)"),
    min_price: Decimal | None = Query(None, ge=0, description="Minimum price filter"),
    max_price: Decimal | None = Query(None, ge=0, description="Maximum price filter"),
    district: str | None = Query(None, description="Filter by district/location (partial match on address)"),
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
