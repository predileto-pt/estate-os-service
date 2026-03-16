from fastapi import APIRouter, Depends, HTTPException, Query, Request

from shared.api.dependencies import get_supabase_user_id
from customer_management.adapters.api.schemas import (
    CreateNotificationRequest,
    MarkNotificationsReadRequest,
    NotificationResponse,
)
from customer_management.domain.exceptions import UserNotFoundError

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _notification_response(n) -> dict:
    return {
        "id": n.id,
        "user_id": n.user_id,
        "title": n.title,
        "message": n.message,
        "status": n.status.value,
        "channel": n.channel,
        "created_at": n.created_at,
        "read_at": n.read_at,
    }


@router.get(
    "",
    response_model=list[NotificationResponse],
    summary="List notifications",
    responses={
        401: {"description": "Not authenticated"},
        404: {"description": "User not found"},
    },
)
async def list_notifications(
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
):
    get_profile_uc = request.app.state.container.get_user_profile
    list_uc = request.app.state.container.list_notifications

    try:
        user, _ = await get_profile_uc.execute(supabase_user_id=supabase_user_id)
    except UserNotFoundError:
        raise HTTPException(status_code=404, detail="User not found")

    notifications = await list_uc.execute(user_id=user.id, limit=limit, offset=offset)
    return [_notification_response(n) for n in notifications]


@router.patch(
    "/read",
    summary="Mark notifications as read",
    responses={
        401: {"description": "Not authenticated"},
        404: {"description": "User not found"},
    },
)
async def mark_notifications_read(
    body: MarkNotificationsReadRequest,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    get_profile_uc = request.app.state.container.get_user_profile
    mark_read_uc = request.app.state.container.mark_notifications_read

    try:
        user, _ = await get_profile_uc.execute(supabase_user_id=supabase_user_id)
    except UserNotFoundError:
        raise HTTPException(status_code=404, detail="User not found")

    count = await mark_read_uc.execute(notification_ids=body.notification_ids, user_id=user.id)
    return {"marked_read": count}


@router.post(
    "",
    response_model=NotificationResponse,
    status_code=201,
    summary="Create notification",
    responses={
        401: {"description": "Not authenticated"},
    },
)
async def create_notification(
    body: CreateNotificationRequest,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    send_uc = request.app.state.container.send_notification

    notification = await send_uc.execute(
        user_id=body.user_id,
        title=body.title,
        message=body.message,
        channel=body.channel,
    )
    return _notification_response(notification)
