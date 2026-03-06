from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from core_api.adapters.api.dependencies import get_supabase_user_id
from core_api.adapters.api.routes.auth import _company_response
from core_api.adapters.api.schemas import CompanyResponse, UpdateCompanyRequest
from core_api.domain.exceptions import AuthorizationError, CompanyNotFoundError, UserNotFoundError
from core_api.domain.models.value_objects import Address

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("/{company_id}", response_model=CompanyResponse)
async def get_company(
    company_id: UUID,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    get_profile_uc = request.app.state.container.get_user_profile

    try:
        user, _ = await get_profile_uc.execute(supabase_user_id=supabase_user_id)
    except UserNotFoundError:
        raise HTTPException(status_code=404, detail="User not found")

    if user.company_id != company_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    company_repo = request.app.state.container.company_repo
    company = await company_repo.get_by_id(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    return _company_response(company)


@router.patch("/{company_id}", response_model=CompanyResponse)
async def update_company(
    company_id: UUID,
    body: UpdateCompanyRequest,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    get_profile_uc = request.app.state.container.get_user_profile
    update_company_uc = request.app.state.container.update_company

    try:
        user, _ = await get_profile_uc.execute(supabase_user_id=supabase_user_id)
    except UserNotFoundError:
        raise HTTPException(status_code=404, detail="User not found")

    address = None
    if body.address_country is not None:
        address = Address(
            street=body.address_street or "",
            parish=body.address_parish,
            municipality=body.address_municipality,
            district=body.address_district,
            postal_code=body.address_postal_code,
            country=body.address_country,
        )

    try:
        company = await update_company_uc.execute(
            company_id=company_id,
            requesting_user_company_id=user.company_id,
            name=body.name,
            tax_id_number=body.tax_id_number,
            address=address,
        )
    except AuthorizationError:
        raise HTTPException(status_code=403, detail="Not authorized")
    except CompanyNotFoundError:
        raise HTTPException(status_code=404, detail="Company not found")

    return _company_response(company)
