from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from core_api.adapters.api.dependencies import get_supabase_user_id
from core_api.adapters.api.schemas import (
    CreateSubscriptionRequest,
    PlanResponse,
    SubscriptionResponse,
    UpdateSubscriptionRequest,
)
from core_api.domain.exceptions import SubscriptionNotFoundError, UserNotFoundError
from core_api.domain.models.subscription import SubscriptionPlan

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


def _subscription_response(sub) -> dict:
    return {
        "id": sub.id,
        "company_id": sub.company_id,
        "plan": sub.plan.value,
        "type": sub.type.value,
        "status": sub.status.value,
        "stripe_subscription_id": sub.stripe_subscription_id,
        "stripe_price_id": sub.stripe_price_id,
        "current_period_start": sub.current_period_start,
        "current_period_end": sub.current_period_end,
        "created_at": sub.created_at,
        "updated_at": sub.updated_at,
    }


@router.get("/plans", response_model=list[PlanResponse], summary="List subscription plans")
async def list_plans():
    return [{"name": p.value, "label": p.value.title()} for p in SubscriptionPlan]


@router.get(
    "/current",
    response_model=SubscriptionResponse,
    summary="Get current subscription",
    responses={
        401: {"description": "Not authenticated"},
        404: {"description": "No active subscription found"},
    },
)
async def get_current_subscription(
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    get_profile_uc = request.app.state.container.get_user_profile

    try:
        user, _ = await get_profile_uc.execute(supabase_user_id=supabase_user_id)
    except UserNotFoundError:
        raise HTTPException(status_code=404, detail="User not found")

    subscription_repo = request.app.state.container.subscription_repo
    sub = await subscription_repo.get_by_company_id(user.company_id)
    if not sub:
        raise HTTPException(status_code=404, detail="No active subscription")

    return _subscription_response(sub)


@router.post(
    "",
    response_model=SubscriptionResponse,
    status_code=201,
    summary="Create subscription",
    responses={
        401: {"description": "Not authenticated"},
        404: {"description": "User not found"},
        422: {"description": "Invalid subscription data"},
    },
)
async def create_subscription(
    body: CreateSubscriptionRequest,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    get_profile_uc = request.app.state.container.get_user_profile
    create_sub_uc = request.app.state.container.create_subscription

    try:
        user, _ = await get_profile_uc.execute(supabase_user_id=supabase_user_id)
    except UserNotFoundError:
        raise HTTPException(status_code=404, detail="User not found")

    sub = await create_sub_uc.execute(
        company_id=user.company_id,
        plan=body.plan,
        type=body.type,
        status=body.status,
        stripe_subscription_id=body.stripe_subscription_id,
        stripe_price_id=body.stripe_price_id,
        current_period_start=body.current_period_start,
        current_period_end=body.current_period_end,
    )
    return _subscription_response(sub)


@router.patch(
    "/{subscription_id}",
    response_model=SubscriptionResponse,
    summary="Update subscription",
    responses={
        401: {"description": "Not authenticated"},
        404: {"description": "Subscription not found"},
        422: {"description": "Invalid subscription data"},
    },
)
async def update_subscription(
    subscription_id: UUID,
    body: UpdateSubscriptionRequest,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    update_sub_uc = request.app.state.container.update_subscription

    try:
        sub = await update_sub_uc.execute(
            subscription_id=subscription_id,
            status=body.status,
            stripe_subscription_id=body.stripe_subscription_id,
            stripe_price_id=body.stripe_price_id,
            current_period_start=body.current_period_start,
            current_period_end=body.current_period_end,
        )
    except SubscriptionNotFoundError:
        raise HTTPException(status_code=404, detail="Subscription not found")

    return _subscription_response(sub)
