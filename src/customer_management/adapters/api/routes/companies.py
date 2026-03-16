from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from shared.api.dependencies import get_supabase_user_id
from customer_management.adapters.api.routes.auth import _company_response
from customer_management.adapters.api.schemas import CompanyResponse, UpdateCompanyRequest
from customer_management.domain.exceptions import (
    AuthorizationError,
    CompanyNotFoundError,
    UserNotFoundError,
)

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get(
    "/{company_id}",
    response_model=CompanyResponse,
    summary="Get company",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Company not found"},
    },
)
async def get_company(
    company_id: UUID,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    get_company_uc = request.app.state.container.get_company

    try:
        company = await get_company_uc.execute(
            supabase_user_id=supabase_user_id, company_id=company_id
        )
    except UserNotFoundError:
        raise HTTPException(status_code=404, detail="User not found")
    except AuthorizationError:
        raise HTTPException(status_code=403, detail="Not authorized")
    except CompanyNotFoundError:
        raise HTTPException(status_code=404, detail="Company not found")

    return _company_response(company)


@router.patch(
    "/{company_id}",
    response_model=CompanyResponse,
    summary="Update company",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Company not found"},
    },
)
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

    try:
        company = await update_company_uc.execute(
            company_id=company_id,
            requesting_user_company_id=user.company_id,
            name=body.name,
            nif=body.nif,
            address=body.address,
        )
    except AuthorizationError:
        raise HTTPException(status_code=403, detail="Not authorized")
    except CompanyNotFoundError:
        raise HTTPException(status_code=404, detail="Company not found")

    return _company_response(company)
