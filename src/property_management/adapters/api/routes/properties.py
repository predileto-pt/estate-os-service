from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from shared.api.dependencies import get_supabase_user_id
from property_management.adapters.api.schemas import (
    CreatePropertyRequest,
    PropertyResponse,
    PropertySummaryResponse,
)
from property_management.domain.exceptions import PropertyNotFoundError

router = APIRouter(prefix="/properties", tags=["properties"])


def _property_response(prop) -> dict:
    characteristics = None
    if prop.characteristics:
        characteristics = prop.characteristics.to_dict()
    return {
        "id": prop.id,
        "organization_id": prop.organization_id,
        "address": prop.address,
        "listing_type": prop.listing_type,
        "typology": prop.typology,
        "status": prop.status,
        "description": prop.description,
        "characteristics": characteristics,
        "latitude": prop.latitude,
        "longitude": prop.longitude,
        "created_at": prop.created_at,
        "updated_at": prop.updated_at,
        "owners": [_owner_response(o) for o in prop.owners],
        "prices": [_price_response(p) for p in prop.prices],
    }


def _price_response(price) -> dict:
    return {
        "id": price.id,
        "property_id": price.property_id,
        "amount": price.amount,
        "listing_type": price.listing_type,
        "created_at": price.created_at,
        "updated_at": price.updated_at,
    }


def _owner_response(owner) -> dict:
    return {
        "id": owner.id,
        "property_id": owner.property_id,
        "full_name": owner.full_name,
        "civil_status": owner.civil_status,
        "address": owner.address,
        "nif": owner.nif,
        "document_type": owner.document_type,
        "document_id": owner.document_id,
        "issued_by": owner.issued_by,
        "issuing_district": owner.issuing_district,
        "date_of_birth": owner.date_of_birth,
        "email": owner.email,
        "phone_number": owner.phone_number,
        "email_verified": owner.email_verified,
        "phone_verified": owner.phone_verified,
        "created_at": owner.created_at,
        "updated_at": owner.updated_at,
    }


@router.post(
    "/",
    response_model=PropertyResponse,
    status_code=201,
    summary="Create property",
    responses={401: {"description": "Not authenticated"}},
)
async def create_property(
    body: CreatePropertyRequest,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    create_uc = request.app.state.property_container.create_property
    prop = await create_uc.execute(
        organization_id=str(body.organization_id),
        address=body.address,
        listing_type=body.listing_type,
        typology=body.typology,
        description=body.description,
    )
    return _property_response(prop)


@router.get(
    "/",
    response_model=list[PropertyResponse],
    summary="List properties",
    responses={401: {"description": "Not authenticated"}},
)
async def list_properties(
    organization_id: UUID,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    list_uc = request.app.state.property_container.list_properties
    props = await list_uc.execute(organization_id=str(organization_id))
    return [_property_response(p) for p in props]


@router.get(
    "/summary",
    response_model=list[PropertySummaryResponse],
    summary="List properties summary",
    responses={401: {"description": "Not authenticated"}},
)
async def list_properties_summary(
    organization_id: UUID,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    list_uc = request.app.state.property_container.list_properties
    props = await list_uc.execute(organization_id=str(organization_id))
    return [
        {
            "id": p.id,
            "address": p.address,
            "listing_type": p.listing_type,
            "typology": p.typology,
            "price": max(p.prices, key=lambda pr: pr.created_at).amount if p.prices else None,
            "owners": [{"full_name": o.full_name} for o in p.owners],
        }
        for p in props
    ]


@router.get(
    "/{property_id}",
    response_model=PropertyResponse,
    summary="Get property",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Property not found"},
    },
)
async def get_property(
    property_id: UUID,
    organization_id: UUID,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    get_uc = request.app.state.property_container.get_property
    try:
        prop = await get_uc.execute(property_id=property_id)
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")

    if str(prop.organization_id) != str(organization_id):
        raise HTTPException(status_code=403, detail="Not authorized")

    return _property_response(prop)
