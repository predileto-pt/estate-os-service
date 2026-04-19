from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from shared.api.dependencies import get_supabase_user_id
from organizations.adapters.api.schemas import (
    MembershipResponse,
    UpdateMemberRoleRequest,
)
from organizations.domain.exceptions import (
    AuthorizationError,
    InsufficientPermissionError,
    LastOwnerError,
    MembershipNotFoundError,
    UserNotFoundError,
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
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    list_members_uc = request.app.state.container.list_members

    try:
        members = await list_members_uc.execute(
            supabase_user_id=supabase_user_id, organization_id=organization_id
        )
    except UserNotFoundError:
        raise HTTPException(status_code=404, detail="User not found")
    except AuthorizationError:
        raise HTTPException(status_code=403, detail="Not authorized")

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
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    update_role_uc = request.app.state.container.update_member_role

    try:
        membership = await update_role_uc.execute(
            supabase_user_id=supabase_user_id,
            membership_id=membership_id,
            new_role=body.role,
        )
    except UserNotFoundError:
        raise HTTPException(status_code=404, detail="User not found")
    except MembershipNotFoundError:
        raise HTTPException(status_code=404, detail="Membership not found")
    except (InsufficientPermissionError, AuthorizationError):
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
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    remove_member_uc = request.app.state.container.remove_member

    try:
        await remove_member_uc.execute(
            supabase_user_id=supabase_user_id,
            membership_id=membership_id,
        )
    except UserNotFoundError:
        raise HTTPException(status_code=404, detail="User not found")
    except MembershipNotFoundError:
        raise HTTPException(status_code=404, detail="Membership not found")
    except (InsufficientPermissionError, AuthorizationError):
        raise HTTPException(status_code=403, detail="Not authorized")
    except LastOwnerError:
        raise HTTPException(status_code=409, detail="Cannot remove the last owner")
