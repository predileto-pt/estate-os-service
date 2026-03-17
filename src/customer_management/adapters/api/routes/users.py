from fastapi import APIRouter, Depends, HTTPException, Request

from shared.api.dependencies import get_supabase_user_id
from customer_management.adapters.api.routes.auth import _organization_response, _user_response
from customer_management.adapters.api.schemas import (
    UpdateUserRequest,
    UserResponse,
    UserWithOrganizationResponse,
)
from customer_management.domain.exceptions import UserNotFoundError
from customer_management.domain.models.value_objects import PhoneNumber

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/me",
    response_model=UserWithOrganizationResponse,
    summary="Get user profile",
    responses={
        401: {"description": "Not authenticated"},
        404: {"description": "User not found"},
    },
)
async def get_user_profile(
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    get_profile_uc = request.app.state.container.get_user_profile

    try:
        user, organization, membership = await get_profile_uc.execute(
            supabase_user_id=supabase_user_id
        )
    except UserNotFoundError:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "user": _user_response(user),
        "organization": _organization_response(organization),
        "role": membership.role.value if membership else None,
    }


@router.patch(
    "/me",
    response_model=UserResponse,
    summary="Update user profile",
    responses={
        401: {"description": "Not authenticated"},
        404: {"description": "User not found"},
    },
)
async def update_user_profile(
    body: UpdateUserRequest,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    get_profile_uc = request.app.state.container.get_user_profile
    update_uc = request.app.state.container.update_user_profile

    try:
        user, _, _ = await get_profile_uc.execute(supabase_user_id=supabase_user_id)
    except UserNotFoundError:
        raise HTTPException(status_code=404, detail="User not found")

    phone = None
    if body.phone_country_code and body.phone_number:
        phone = PhoneNumber(country_code=body.phone_country_code, number=body.phone_number)

    updated = await update_uc.execute(
        user_id=user.id,
        name=body.name,
        phone=phone,
    )
    return _user_response(updated)
