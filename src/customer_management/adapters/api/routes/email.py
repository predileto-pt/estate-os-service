from fastapi import APIRouter, Depends, Request

from shared.api.dependencies import get_supabase_user_id
from customer_management.adapters.api.schemas import SendEmailRequest

router = APIRouter(prefix="/email", tags=["email"])


@router.post(
    "/send",
    summary="Send email",
    responses={
        401: {"description": "Not authenticated"},
    },
)
async def send_email(
    body: SendEmailRequest,
    request: Request,
    _: str = Depends(get_supabase_user_id),
):
    email_service = request.app.state.container.email_service

    await email_service.send(
        to=body.to,
        subject=body.subject,
        html=body.html,
        from_email=body.from_email,
    )
    return {"status": "sent"}
