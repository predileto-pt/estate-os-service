"""Admin registration endpoint — `POST /api/v1/admin/auth/register`.

Invokes `RegisterAdminAccount` which (per Q3 = 3.a): calls identity's
idempotent RegisterUser, checks for existing memberships (409 if found),
then creates Org + OwnerMembership + Subscription in a single
organizations-local transaction.
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from identity.adapters.api.schemas import UserResponse
from identity.domain.value_objects import PhoneNumber
from organizations.application.use_cases.register_admin_account import (
    AdminAccountAlreadyExistsError,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class AdminRegisterRequest(BaseModel):
    name: str
    email: str
    organization_name: str | None = None
    phone_country_code: str | None = Field(default=None, description="E.g. +351")
    phone_number: str | None = None


class OrganizationSummary(BaseModel):
    id: str
    name: str | None
    nif: str | None
    created_at: str
    updated_at: str


class MembershipSummary(BaseModel):
    id: str
    role: str
    organization_id: str
    created_at: str


class SubscriptionSummary(BaseModel):
    id: str | None
    plan: str | None
    status: str | None


class AdminRegisterResponse(BaseModel):
    user: UserResponse
    organization: OrganizationSummary
    membership: MembershipSummary
    subscription: SubscriptionSummary | None


@router.post(
    "/register",
    response_model=AdminRegisterResponse,
    summary="Register admin account (user + organization + owner membership)",
    responses={
        401: {"description": "Not authenticated"},
        409: {"description": "Admin account already exists"},
        422: {"description": "Invalid request body"},
    },
)
async def register_admin(body: AdminRegisterRequest, request: Request):
    supabase_user_id = getattr(request.state, "supabase_user_id", None)
    if not supabase_user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    register_uc = request.app.state.organizations_container.register_admin_account

    phone = None
    if body.phone_country_code and body.phone_number:
        phone = PhoneNumber(country_code=body.phone_country_code, number=body.phone_number)

    try:
        user, organization, membership, subscription = await register_uc.execute(
            supabase_user_id=supabase_user_id,
            email=body.email,
            name=body.name,
            organization_name=body.organization_name,
            phone=phone,
        )
    except AdminAccountAlreadyExistsError:
        raise HTTPException(status_code=409, detail="Admin account already exists")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {
        "user": {
            "id": str(user.id),
            "supabase_user_id": user.supabase_user_id,
            "email": user.email,
            "name": user.name,
            "phone": (
                {"country_code": user.phone.country_code, "number": user.phone.number}
                if user.phone
                else None
            ),
            "created_at": str(user.created_at),
            "updated_at": str(user.updated_at),
        },
        "organization": {
            "id": str(organization.id),
            "name": organization.name,
            "nif": organization.nif,
            "created_at": str(organization.created_at),
            "updated_at": str(organization.updated_at),
        },
        "membership": {
            "id": str(membership.id),
            "role": membership.role.value,
            "organization_id": str(membership.organization_id),
            "created_at": str(membership.created_at),
        },
        "subscription": (
            {
                "id": str(subscription.id),
                "plan": subscription.plan.value,
                "status": subscription.status.value,
            }
            if subscription
            else None
        ),
    }
