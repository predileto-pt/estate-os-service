from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from shared.api.dependencies import get_supabase_user_id
from organizations.adapters.api.routes.auth import _organization_response
from organizations.adapters.api.schemas import (
    OrganizationResponse,
    UpdateOrganizationRequest,
)
from organizations.domain.exceptions import (
    AuthorizationError,
    InsufficientPermissionError,
    OrganizationNotFoundError,
    UserNotFoundError,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get(
    "/{organization_id}",
    response_model=OrganizationResponse,
    summary="Get organization",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Organization not found"},
    },
)
async def get_organization(
    organization_id: UUID,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    get_organization_uc = request.app.state.container.get_organization

    try:
        organization = await get_organization_uc.execute(
            supabase_user_id=supabase_user_id, organization_id=organization_id
        )
    except UserNotFoundError:
        raise HTTPException(status_code=404, detail="User not found")
    except AuthorizationError:
        raise HTTPException(status_code=403, detail="Not authorized")
    except OrganizationNotFoundError:
        raise HTTPException(status_code=404, detail="Organization not found")

    return _organization_response(organization)


@router.patch(
    "/{organization_id}",
    response_model=OrganizationResponse,
    summary="Update organization",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Organization not found"},
    },
)
async def update_organization(
    organization_id: UUID,
    body: UpdateOrganizationRequest,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    update_organization_uc = request.app.state.container.update_organization

    try:
        organization = await update_organization_uc.execute(
            organization_id=organization_id,
            supabase_user_id=supabase_user_id,
            name=body.name,
            nif=body.nif,
            address=body.address,
        )
    except UserNotFoundError:
        raise HTTPException(status_code=404, detail="User not found")
    except (AuthorizationError, InsufficientPermissionError):
        raise HTTPException(status_code=403, detail="Not authorized")
    except OrganizationNotFoundError:
        raise HTTPException(status_code=404, detail="Organization not found")

    return _organization_response(organization)
