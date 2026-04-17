from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from customers.domain.models.membership import Membership
from customers.domain.models.user import User
from shared.api.dependencies import (
    assert_org_member,
    get_supabase_user_id,
    require_org_member,
)
from properties.adapters.api.routes.properties import _property_response
from properties.adapters.api.schemas import (
    CreatePropertyPriceRequest,
    PropertyPriceResponse,
    PropertyResponse,
)
from properties.domain.exceptions import PropertyNotFoundError

router = APIRouter(prefix="/property-prices", tags=["property-prices"])


async def _verify_property_ownership(
    request: Request, property_id: UUID, organization_id: UUID
) -> None:
    get_prop_uc = request.app.state.property_container.get_property
    try:
        await get_prop_uc.execute(property_id=property_id, organization_id=organization_id)
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")


@router.post(
    "/",
    response_model=PropertyResponse,
    status_code=201,
    summary="Create property price",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Property not found"},
    },
)
async def create_property_price(
    body: CreatePropertyPriceRequest,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    await assert_org_member(request, supabase_user_id, body.organization_id)
    await _verify_property_ownership(request, body.property_id, body.organization_id)

    create_uc = request.app.state.property_container.create_property_price
    try:
        prop = await create_uc.execute(
            property_id=body.property_id,
            amount=body.amount,
            listing_type=body.listing_type,
        )
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")

    return _property_response(prop)


@router.get(
    "/",
    response_model=list[PropertyPriceResponse],
    summary="List property prices",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
    },
)
async def list_property_prices(
    property_id: UUID,
    organization_id: UUID,
    request: Request,
    _member: tuple[User, Membership] = Depends(require_org_member),
):
    await _verify_property_ownership(request, property_id, organization_id)

    list_uc = request.app.state.property_container.list_property_prices
    prices = await list_uc.execute(property_id=property_id)
    return [
        {
            "id": p.id,
            "property_id": p.property_id,
            "amount": p.amount,
            "listing_type": p.listing_type,
            "created_at": p.created_at,
            "updated_at": p.updated_at,
        }
        for p in prices
    ]
