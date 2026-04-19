"""Portal registration endpoint.

`POST /auth/register` (mounted at `/api/v1/portal` in main.py).
Calls `identity.RegisterUser` which is idempotent on `supabase_user_id`
— duplicate calls return the existing User as 200, not 409.

The admin counterpart lives in `organizations.adapters.api.routes.admin_auth`
and uses the compound `RegisterAdminAccount` use case.
"""

from fastapi import APIRouter, Request

from identity.adapters.api.schemas import RegisterRequest, UserResponse
from identity.domain.value_objects import PhoneNumber

router = APIRouter(prefix="/auth", tags=["portal"])


def _user_response(user) -> dict:
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
    response_model=UserResponse,
    summary="Register portal user",
    responses={
        401: {"description": "Not authenticated"},
    },
)
async def register(body: RegisterRequest, request: Request):
    register_uc = request.app.state.identity_container.register_user
    supabase_user_id = request.state.supabase_user_id

    phone = None
    if body.phone_country_code and body.phone_number:
        phone = PhoneNumber(country_code=body.phone_country_code, number=body.phone_number)

    user = await register_uc.execute(
        supabase_user_id=supabase_user_id,
        email=body.email,
        name=body.name,
        phone=phone,
    )
    return _user_response(user)
