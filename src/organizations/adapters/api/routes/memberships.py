from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from identity.domain.models.user import User
from organizations.domain.models.membership import Membership
from shared.api.dependencies import get_current_user, require_org_member
from organizations.adapters.api.schemas import (
    MembershipResponse,
    UpdateMemberRoleRequest,
)
from organizations.domain.exceptions import (
    InsufficientPermissionError,
    LastOwnerError,
    MembershipNotFoundError,
)

router = APIRouter(prefix="/memberships", tags=["memberships"])


def _membership_response(membership) -> dict:
    return {
        "id": membership.id,
        "user_id": membership.user_id,
        "organization_id": membership.organization_id,
        "role": membership.role.value,
        "created_at": membership.created_at,
        "updated_at": membership.updated_at,
    }


@router.get(
    "",
    response_model=list[MembershipResponse],
    summary="List organization members",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
    },
)
async def list_members(
    request: Request,
    organization_id: UUID,
    _member: tuple[User, Membership] = Depends(require_org_member),
):
    membership_repo = request.app.state.container.membership_repo
    members = await membership_repo.list_by_organization(organization_id)
    return [_membership_response(m) for m in members]


@router.patch(
    "/{membership_id}",
    response_model=MembershipResponse,
    summary="Update member role",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Membership not found"},
        409: {"description": "Cannot demote last owner"},
    },
)
async def update_member_role(
    membership_id: UUID,
    body: UpdateMemberRoleRequest,
    request: Request,
    user: User = Depends(get_current_user),
):
    update_role_uc = request.app.state.container.update_member_role

    try:
        membership = await update_role_uc.execute(
            requester_user_id=user.id,
            membership_id=membership_id,
            new_role=body.role,
        )
    except MembershipNotFoundError:
        raise HTTPException(status_code=404, detail="Membership not found")
    except InsufficientPermissionError:
        raise HTTPException(status_code=403, detail="Not authorized")
    except LastOwnerError:
        raise HTTPException(status_code=409, detail="Cannot demote the last owner")

    return _membership_response(membership)


@router.delete(
    "/{membership_id}",
    status_code=204,
    summary="Remove member",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Membership not found"},
        409: {"description": "Cannot remove last owner"},
    },
)
async def remove_member(
    membership_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
):
    remove_member_uc = request.app.state.container.remove_member

    try:
        await remove_member_uc.execute(
            requester_user_id=user.id,
            membership_id=membership_id,
        )
    except MembershipNotFoundError:
        raise HTTPException(status_code=404, detail="Membership not found")
    except InsufficientPermissionError:
        raise HTTPException(status_code=403, detail="Not authorized")
    except LastOwnerError:
        raise HTTPException(status_code=409, detail="Cannot remove the last owner")
