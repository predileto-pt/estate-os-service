from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from identity.domain.models.user import User
from shared.api.dependencies import get_current_user
from organizations.adapters.api.schemas import (
    InvitationResponse,
    InviteMemberRequest,
)
from organizations.domain.exceptions import (
    AuthorizationError,
    InsufficientPermissionError,
    InvitationNotFoundError,
    MembershipAlreadyExistsError,
)

router = APIRouter(prefix="/invitations", tags=["invitations"])


def _invitation_response(invitation) -> dict:
    return {
        "id": invitation.id,
        "email": invitation.email,
        "role": invitation.role.value,
        "status": invitation.status.value,
        "invited_by": invitation.invited_by,
        "organization_id": invitation.organization_id,
        "expires_at": invitation.expires_at,
        "created_at": invitation.created_at,
    }


@router.post(
    "",
    response_model=InvitationResponse,
    status_code=201,
    summary="Invite user by email",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        409: {"description": "User is already a member"},
    },
)
async def invite_member(
    body: InviteMemberRequest,
    request: Request,
    organization_id: UUID,
    user: User = Depends(get_current_user),
):
    invite_uc = request.app.state.container.invite_member

    try:
        invitation = await invite_uc.execute(
            inviter_user_id=user.id,
            organization_id=organization_id,
            email=body.email,
            role=body.role,
        )
    except (InsufficientPermissionError, AuthorizationError):
        raise HTTPException(status_code=403, detail="Not authorized")
    except MembershipAlreadyExistsError:
        raise HTTPException(status_code=409, detail="User is already a member")

    return _invitation_response(invitation)


@router.get(
    "",
    response_model=list[InvitationResponse],
    summary="List pending invitations",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
    },
)
async def list_invitations(
    request: Request,
    organization_id: UUID,
    user: User = Depends(get_current_user),
):
    list_invitations_uc = request.app.state.container.list_invitations

    try:
        invitations = await list_invitations_uc.execute(
            requester_user_id=user.id, organization_id=organization_id
        )
    except AuthorizationError:
        raise HTTPException(status_code=403, detail="Not authorized")

    return [_invitation_response(inv) for inv in invitations]


@router.delete(
    "/{invitation_id}",
    status_code=204,
    summary="Revoke invitation",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Invitation not found"},
    },
)
async def revoke_invitation(
    invitation_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
):
    revoke_uc = request.app.state.container.revoke_invitation

    try:
        await revoke_uc.execute(
            requester_user_id=user.id,
            invitation_id=invitation_id,
        )
    except InvitationNotFoundError:
        raise HTTPException(status_code=404, detail="Invitation not found")
    except (InsufficientPermissionError, AuthorizationError):
        raise HTTPException(status_code=403, detail="Not authorized")
