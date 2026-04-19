from fastapi import APIRouter, HTTPException, Request

from organizations.adapters.api.schemas import (
    RegisterRequest,
    UserResponse,
)
from organizations.domain.exceptions import UserAlreadyExistsError
from organizations.domain.models.value_objects import PhoneNumber

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_response(user) -> dict:
    return {
        "id": user.id,
        "supabase_user_id": user.supabase_user_id,
        "email": user.email,
        "name": user.name,
        "phone": (
            {"country_code": user.phone.country_code, "number": user.phone.number}
            if user.phone
            else None
        ),
        "organization_id": user.organization_id,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


def _organization_response(organization) -> dict | None:
    if not organization:
        return None
    return {
        "id": organization.id,
        "created_by": organization.created_by,
        "name": organization.name,
        "nif": organization.nif,
        "address": organization.address,
        "created_at": organization.created_at,
        "updated_at": organization.updated_at,
    }


@router.post(
    "/register",
    response_model=UserResponse,
    summary="Register user",
    responses={
        401: {"description": "Not authenticated"},
        409: {"description": "User already exists"},
    },
)
async def register(body: RegisterRequest, request: Request):
    register_uc = request.app.state.container.register_user

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
            organization_name=body.organization_name,
            phone=phone,
        )
    except UserAlreadyExistsError:
        raise HTTPException(status_code=409, detail="User already exists")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return _user_response(user)


# GET /me moved to `identity.adapters.api.routes.me` — same endpoint
# path, now served by identity and reading request.state populated by
# IdentityMiddleware. Old handler removed in the identity-split commit.
