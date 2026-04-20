from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from billing.application.ports.billing_gateway import SignatureVerificationError
from billing.domain.exceptions import (
    BillingCustomerMissingError,
    UnknownStripePriceError,
)
from billing.domain.models.subscription import SubscriptionPlan
from identity.domain.models.user import User
from organizations.domain.models.membership import Membership
from shared.api.dependencies import (
    require_current_org,
    require_current_org_admin,
)

log = structlog.get_logger()

admin_router = APIRouter(prefix="/billing", tags=["billing"])
webhook_router = APIRouter(prefix="/billing/webhooks", tags=["billing"])


class CheckoutRequest(BaseModel):
    plan: Literal["pro", "enterprise"]
    cadence: Literal["monthly", "yearly"]


class CheckoutResponse(BaseModel):
    url: str
    session_id: str


class PortalResponse(BaseModel):
    url: str


class SubscriptionResponse(BaseModel):
    id: str | None
    organization_id: str
    plan: str
    type: str
    status: str
    cadence: Literal["monthly", "yearly"] | None = None
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    stripe_price_id: str | None = None
    current_period_start: str | None = None
    current_period_end: str | None = None


class PlanResponse(BaseModel):
    name: str
    label: str


def _subscription_response(sub, organization_id, price_catalog) -> dict:
    if sub is None:
        return {
            "id": None,
            "organization_id": str(organization_id),
            "plan": SubscriptionPlan.FREEMIUM.value,
            "type": "manual",
            "status": "active",
        }

    cadence: Literal["monthly", "yearly"] | None = None
    if sub.stripe_price_id:
        if sub.stripe_price_id in (
            price_catalog.pro_monthly,
            price_catalog.enterprise_monthly,
        ):
            cadence = "monthly"
        elif sub.stripe_price_id in (
            price_catalog.pro_yearly,
            price_catalog.enterprise_yearly,
        ):
            cadence = "yearly"

    return {
        "id": str(sub.id),
        "organization_id": str(sub.organization_id),
        "plan": sub.plan.value,
        "type": sub.type.value,
        "status": sub.status.value,
        "cadence": cadence,
        "stripe_customer_id": sub.stripe_customer_id,
        "stripe_subscription_id": sub.stripe_subscription_id,
        "stripe_price_id": sub.stripe_price_id,
        "current_period_start": (
            sub.current_period_start.isoformat() if sub.current_period_start else None
        ),
        "current_period_end": (
            sub.current_period_end.isoformat() if sub.current_period_end else None
        ),
    }


# ── admin (authenticated, OWNER/ADMIN for writes) ────────────────────────────


@admin_router.get(
    "/plans",
    response_model=list[PlanResponse],
    summary="List available subscription plans",
)
async def list_plans():
    return [{"name": p.value, "label": p.value.title()} for p in SubscriptionPlan]


@admin_router.get(
    "/subscription",
    response_model=SubscriptionResponse,
    summary="Get current organization's subscription",
)
async def get_current_subscription(
    request: Request,
    member: tuple[User, Membership] = Depends(require_current_org),
):
    _, membership = member
    container = request.app.state.billing_container
    sub = await container.subscription_repo.get_by_organization_id(membership.organization_id)
    return _subscription_response(sub, membership.organization_id, container.price_catalog)


@admin_router.post(
    "/checkout",
    response_model=CheckoutResponse,
    summary="Start a Stripe Checkout session for the current org",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not an admin of this organization"},
        422: {"description": "Unknown plan / cadence combination"},
    },
)
async def start_checkout(
    body: CheckoutRequest,
    request: Request,
    member: tuple[User, Membership] = Depends(require_current_org_admin),
):
    user, membership = member
    container = request.app.state.billing_container

    try:
        session = await container.start_checkout_session.execute(
            organization_id=membership.organization_id,
            plan=SubscriptionPlan(body.plan),
            cadence=body.cadence,
            billing_email=user.email,
            billing_name=user.name,
        )
    except UnknownStripePriceError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"url": session.url, "session_id": session.id}


@admin_router.post(
    "/portal",
    response_model=PortalResponse,
    summary="Start a Stripe Customer Portal session",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not an admin of this organization"},
        409: {"description": "Organization has no Stripe customer yet"},
    },
)
async def start_portal(
    request: Request,
    member: tuple[User, Membership] = Depends(require_current_org_admin),
):
    _, membership = member
    container = request.app.state.billing_container

    try:
        url = await container.start_billing_portal_session.execute(
            organization_id=membership.organization_id
        )
    except BillingCustomerMissingError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return {"url": url}


# ── webhooks (unauthenticated, signature-verified) ───────────────────────────


@webhook_router.post(
    "/stripe",
    summary="Stripe webhook endpoint",
    responses={
        200: {"description": "Event processed"},
        400: {"description": "Invalid signature"},
    },
)
async def stripe_webhook(request: Request):
    container = request.app.state.billing_container
    gateway = container.billing_gateway

    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")

    try:
        event = gateway.verify_webhook(payload=payload, signature=signature)
    except SignatureVerificationError:
        log.warning("stripe_webhook.bad_signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    await container.handle_stripe_webhook.execute(event)
    return {"received": True}
