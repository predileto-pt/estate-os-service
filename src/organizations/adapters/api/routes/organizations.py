from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from identity.domain.models.user import User
from shared.api.dependencies import get_current_user
from organizations.adapters.api.schemas import (
    OrganizationResponse,
    UpdateOrganizationRequest,
)
from organizations.domain.exceptions import (
    AuthorizationError,
    InsufficientPermissionError,
    OrganizationNotFoundError,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


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
    user: User = Depends(get_current_user),
):
    get_organization_uc = request.app.state.container.get_organization

    try:
        organization = await get_organization_uc.execute(
            requester_user_id=user.id, organization_id=organization_id
        )
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
    user: User = Depends(get_current_user),
):
    update_organization_uc = request.app.state.container.update_organization

    try:
        organization = await update_organization_uc.execute(
            organization_id=organization_id,
            requester_user_id=user.id,
            name=body.name,
            nif=body.nif,
            address=body.address,
        )
    except (AuthorizationError, InsufficientPermissionError):
        raise HTTPException(status_code=403, detail="Not authorized")
    except OrganizationNotFoundError:
        raise HTTPException(status_code=404, detail="Organization not found")

    return _organization_response(organization)
