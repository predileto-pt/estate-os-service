from fastapi import APIRouter, HTTPException, Request

from identity.adapters.api.schemas import UpdateProfileRequest, UserResponse
from identity.domain.exceptions import UserNotFoundError
from identity.domain.value_objects import PhoneNumber

router = APIRouter(prefix="/auth", tags=["auth"])


@router.patch(
    "/profile",
    response_model=UserResponse,
    summary="Update the current user's profile",
    responses={
        401: {"description": "Not authenticated"},
    },
)
async def update_profile(body: UpdateProfileRequest, request: Request):
    user = request.state.user
    update_uc = request.app.state.identity_container.update_user_profile

    phone: PhoneNumber | None | object = UpdateProfileRequest
    if body.phone_country_code is None and body.phone_number is None:
        # Caller did not provide phone at all — leave unchanged.
        phone = update_uc._SENTINEL
    elif body.phone_country_code and body.phone_number:
        phone = PhoneNumber(country_code=body.phone_country_code, number=body.phone_number)
    else:
        phone = None  # explicit clear

    try:
        updated = await update_uc.execute(user_id=user.id, name=body.name, phone=phone)
    except UserNotFoundError:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "id": str(updated.id),
        "supabase_user_id": updated.supabase_user_id,
        "email": updated.email,
        "name": updated.name,
        "phone": (
            {"country_code": updated.phone.country_code, "number": updated.phone.number}
            if updated.phone
            else None
        ),
        "created_at": str(updated.created_at),
        "updated_at": str(updated.updated_at),
    }
