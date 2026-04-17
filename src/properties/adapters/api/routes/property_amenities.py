from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from customers.domain.models.membership import Membership
from customers.domain.models.user import User
from shared.api.dependencies import require_org_member
from shared.events.base import DomainEvent
from shared.events.types import PROPERTY_CREATED
from properties.adapters.api.schemas import PropertyAmenityResponse
from properties.domain.exceptions import PropertyNotFoundError

router = APIRouter(prefix="/property-amenities", tags=["property-amenities"])


async def _verify_property_ownership(
    request: Request, property_id: UUID, organization_id: UUID
) -> None:
    get_prop_uc = request.app.state.property_container.get_property
    try:
        await get_prop_uc.execute(property_id=property_id, organization_id=organization_id)
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")


@router.get(
    "/",
    response_model=list[PropertyAmenityResponse],
    summary="List property amenities",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Property not found"},
    },
)
async def get_property_amenities(
    property_id: UUID,
    organization_id: UUID,
    request: Request,
    _member: tuple[User, Membership] = Depends(require_org_member),
):
    await _verify_property_ownership(request, property_id, organization_id)

    get_uc = request.app.state.property_container.get_property_amenities
    try:
        amenities = await get_uc.execute(property_id=str(property_id))
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")

    return [
        {
            "id": a.id,
            "property_id": a.property_id,
            "category": a.category,
            "nearest_name": a.nearest_name,
            "nearest_distance_meters": a.nearest_distance_meters,
            "nearest_latitude": a.nearest_latitude,
            "nearest_longitude": a.nearest_longitude,
            "total_count": a.total_count,
            "nearest_place_id": a.nearest_place_id,
            "nearest_google_maps_url": a.nearest_google_maps_url,
            "top_places": [p.to_dict() for p in a.top_places],
            "created_at": a.created_at,
            "updated_at": a.updated_at,
        }
        for a in amenities
    ]


@router.post(
    "/discover",
    status_code=202,
    summary="Trigger amenity discovery for a property",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Property not found"},
        422: {"description": "Property missing coordinates"},
    },
)
async def discover_property_amenities(
    property_id: UUID,
    organization_id: UUID,
    request: Request,
    _member: tuple[User, Membership] = Depends(require_org_member),
):
    await _verify_property_ownership(request, property_id, organization_id)

    domain_event_publisher = request.app.state.property_container.domain_event_publisher
    if not domain_event_publisher:
        raise HTTPException(status_code=503, detail="Discovery service not available")

    try:
        prop = await request.app.state.property_container.get_property.execute(
            property_id=property_id, organization_id=organization_id
        )
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")

    if prop.latitude is None or prop.longitude is None:
        raise HTTPException(status_code=422, detail="Property missing coordinates")

    await domain_event_publisher.publish(
        DomainEvent(event_type=PROPERTY_CREATED, data={"property_id": str(property_id)})
    )

    return {"status": "discovery_triggered", "property_id": str(property_id)}
