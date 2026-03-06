from fastapi import APIRouter, Depends, HTTPException, Request

from core_api.adapters.api.dependencies import get_supabase_user_id
from core_api.adapters.api.schemas import RegisterRequest, UserResponse, UserWithCompanyResponse
from core_api.domain.exceptions import UserAlreadyExistsError, UserNotFoundError
from core_api.domain.models.value_objects import Address, PhoneNumber

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
        "company_id": user.company_id,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


def _company_response(company) -> dict | None:
    if not company:
        return None
    return {
        "id": company.id,
        "name": company.name,
        "tax_id_number": company.tax_id_number,
        "address": {
            "street": company.address.street,
            "parish": company.address.parish,
            "municipality": company.address.municipality,
            "district": company.address.district,
            "postal_code": company.address.postal_code,
            "country": company.address.country,
        },
        "stripe_customer_id": company.stripe_customer_id,
        "created_at": company.created_at,
        "updated_at": company.updated_at,
    }


@router.post("/register", response_model=UserResponse)
async def register(body: RegisterRequest, request: Request):
    register_uc = request.app.state.container.register_user

    phone = None
    if body.phone_country_code and body.phone_number:
        phone = PhoneNumber(country_code=body.phone_country_code, number=body.phone_number)

    address = Address(
        street=body.address_street,
        parish=body.address_parish,
        municipality=body.address_municipality,
        district=body.address_district,
        postal_code=body.address_postal_code,
        country=body.address_country,
    )

    supabase_user_id = getattr(request.state, "supabase_user_id", None)
    if not supabase_user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        user = await register_uc.execute(
            supabase_user_id=supabase_user_id,
            email=body.email,
            name=body.name,
            company_name=body.company_name,
            tax_id_number=body.tax_id_number,
            address=address,
            phone=phone,
        )
    except UserAlreadyExistsError:
        raise HTTPException(status_code=409, detail="User already exists")

    return _user_response(user)


@router.get("/me", response_model=UserWithCompanyResponse)
async def get_me(
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    get_profile_uc = request.app.state.container.get_user_profile

    try:
        user, company = await get_profile_uc.execute(supabase_user_id=supabase_user_id)
    except UserNotFoundError:
        raise HTTPException(status_code=404, detail="User not found")

    return {"user": _user_response(user), "company": _company_response(company)}
