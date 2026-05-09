from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from identity.domain.models.user import User
from organizations.domain.models.membership import Membership
from properties.adapters.api.schemas import (
    PropertyPoiResponse,
    ReplacePropertyPoisRequest,
    UpdatePropertyPoiRequest,
)
from properties.application.use_cases.replace_property_pois import PoiInput
from properties.application.use_cases.update_property_poi import PoiPatch
from properties.domain.exceptions import PropertyNotFoundError
from properties.domain.models.property_poi import PropertyPoi
from shared.api.dependencies import require_org_member

router = APIRouter(prefix="/properties", tags=["property-pois"])


def _poi_response(poi: PropertyPoi) -> dict:
    return {
        "id": poi.id,
        "property_id": poi.property_id,
        "category": poi.category,
        "name": poi.name,
        "distance_meters": poi.distance_meters,
        "latitude": poi.latitude,
        "longitude": poi.longitude,
        "place_type": poi.place_type,
        "place_id": poi.place_id,
        "metadata": poi.metadata,
        "manually_edited": poi.manually_edited,
        "address": poi.address,
        "image_urls": poi.image_urls,
        "reviews": poi.reviews,
        "created_at": poi.created_at,
        "updated_at": poi.updated_at,
    }


@router.get(
    "/{property_id}/pois",
    response_model=list[PropertyPoiResponse],
    summary="List a property's POIs",
    responses={
        200: {"description": "POIs for the property"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not a member of this organization"},
        404: {"description": "Property not found"},
    },
)
async def list_property_pois(
    property_id: UUID,
    organization_id: UUID,
    request: Request,
    _member: tuple[User, Membership] = Depends(require_org_member),
):
    use_case = request.app.state.property_container.list_property_pois
    try:
        pois = await use_case.execute(property_id=property_id, organization_id=organization_id)
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")
    return [_poi_response(p) for p in pois]


@router.post(
    "/{property_id}/pois",
    response_model=list[PropertyPoiResponse],
    status_code=200,
    summary="Replace the entire POI catalog for a property",
    description=(
        "Replaces every existing POI for this property with the supplied list. "
        "Each row is flagged `manually_edited=true` so the future enrichment "
        "workflow won't re-discover categories with manually-edited rows. "
        "Empty list (`pois: []`) clears the catalog."
    ),
    responses={
        200: {"description": "POIs replaced (or catalog cleared on empty list)"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not a member of this organization"},
        404: {"description": "Property not found"},
        422: {"description": "Invalid body"},
    },
)
async def replace_property_pois(
    property_id: UUID,
    organization_id: UUID,
    body: ReplacePropertyPoisRequest,
    request: Request,
    _member: tuple[User, Membership] = Depends(require_org_member),
):
    use_case = request.app.state.property_container.replace_property_pois
    inputs = [
        PoiInput(
            category=p.category,
            name=p.name,
            distance_meters=p.distance_meters,
            latitude=p.latitude,
            longitude=p.longitude,
            place_type=p.place_type,
            place_id=p.place_id,
            metadata=p.metadata,
            address=p.address,
            image_urls=p.image_urls,
            reviews=p.reviews,
        )
        for p in body.pois
    ]
    try:
        persisted = await use_case.execute(
            property_id=property_id,
            organization_id=organization_id,
            pois=inputs,
        )
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")
    return [_poi_response(p) for p in persisted]


@router.patch(
    "/{property_id}/pois/{poi_id}",
    response_model=PropertyPoiResponse,
    summary="Edit one POI in place",
    description=(
        "Partial update. Sets `manually_edited=true` on success. Cross-property "
        "defense: returns 404 if `poi_id` exists but belongs to a different property."
    ),
    responses={
        200: {"description": "POI updated"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not a member of this organization"},
        404: {"description": "Property or POI not found"},
        422: {"description": "Invalid body"},
    },
)
async def update_property_poi(
    property_id: UUID,
    poi_id: UUID,
    organization_id: UUID,
    body: UpdatePropertyPoiRequest,
    request: Request,
    _member: tuple[User, Membership] = Depends(require_org_member),
):
    use_case = request.app.state.property_container.update_property_poi
    # Detect explicit nulling of `reviews` so the use case can clear it.
    # `body.reviews` is None either when omitted or when explicitly null —
    # we use Pydantic's `model_fields_set` to disambiguate.
    body_set = body.model_fields_set
    clear_reviews = "reviews" in body_set and body.reviews is None
    patch = PoiPatch(
        category=body.category,
        name=body.name,
        distance_meters=body.distance_meters,
        latitude=body.latitude,
        longitude=body.longitude,
        place_type=body.place_type,
        place_id=body.place_id,
        metadata=body.metadata,
        address=body.address,
        image_urls=body.image_urls,
        reviews=body.reviews,
        clear_reviews=clear_reviews,
    )
    try:
        persisted = await use_case.execute(
            property_id=property_id,
            organization_id=organization_id,
            poi_id=poi_id,
            patch=patch,
        )
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="POI not found")
    return _poi_response(persisted)


@router.delete(
    "/{property_id}/pois/{poi_id}",
    status_code=204,
    summary="Delete one POI",
    responses={
        204: {"description": "POI deleted"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not a member of this organization"},
        404: {"description": "Property or POI not found"},
    },
)
async def delete_property_poi(
    property_id: UUID,
    poi_id: UUID,
    organization_id: UUID,
    request: Request,
    _member: tuple[User, Membership] = Depends(require_org_member),
):
    use_case = request.app.state.property_container.delete_property_poi
    try:
        await use_case.execute(
            property_id=property_id,
            organization_id=organization_id,
            poi_id=poi_id,
        )
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="POI not found")
    return None
