from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from shared.api.dependencies import get_supabase_user_id
from organizations.domain.exceptions import (
    PortalUserAlreadyExistsError,
    PortalUserNotFoundError,
)
from organizations.domain.models.value_objects import PhoneNumber

router = APIRouter(prefix="/auth", tags=["portal"])


class PortalRegisterRequest(BaseModel):
    name: str
    email: str
    phone_country_code: str | None = Field(default=None, description="E.g. +351")
    phone_number: str | None = None


class PortalUserResponse(BaseModel):
    id: str
    supabase_user_id: str
    email: str
    name: str
    phone: dict | None = None
    created_at: str
    updated_at: str


def _portal_user_response(user) -> dict:
    return {
        "id": str(user.id),
        "supabase_user_id": user.supabase_user_id,
        "email": user.email,
        "name": user.name,
        "phone": (
            {"country_code": user.phone.country_code, "number": user.phone.number}
            if user.phone
            else None
        ),
        "created_at": str(user.created_at),
        "updated_at": str(user.updated_at),
    }


@router.post(
    "/register",
    response_model=PortalUserResponse,
    summary="Register portal user",
    responses={
        401: {"description": "Not authenticated"},
        409: {"description": "Portal user already exists"},
    },
)
async def register(body: PortalRegisterRequest, request: Request):
    register_uc = request.app.state.container.register_portal_user

    phone = None
    if body.phone_country_code and body.phone_number:
        phone = PhoneNumber(country_code=body.phone_country_code, number=body.phone_number)

    supabase_user_id = getattr(request.state, "supabase_user_id", None)
    if not supabase_user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        user = await register_uc.execute(
            supabase_user_id=supabase_user_id,
            email=body.email,
            name=body.name,
            phone=phone,
        )
    except PortalUserAlreadyExistsError:
        raise HTTPException(status_code=409, detail="Portal user already exists")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return _portal_user_response(user)


@router.get(
    "/me",
    response_model=PortalUserResponse,
    summary="Get authenticated portal user",
    responses={
        401: {"description": "Not authenticated"},
        404: {"description": "Portal user not found"},
    },
)
async def get_me(
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    get_profile_uc = request.app.state.container.get_portal_user

    try:
        user = await get_profile_uc.execute(supabase_user_id=supabase_user_id)
    except PortalUserNotFoundError:
        raise HTTPException(status_code=404, detail="Portal user not found")

    return _portal_user_response(user)
