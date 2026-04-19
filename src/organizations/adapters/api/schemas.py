from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from organizations.domain.models.invitation import InvitationStatus
from organizations.domain.models.membership import MembershipRole
from organizations.domain.models.notification import NotificationStatus
from organizations.domain.models.subscription import (
    SubscriptionPlan,
    SubscriptionStatus,
    SubscriptionType,
)


# --- Auth ---
class RegisterRequest(BaseModel):
    name: str
    email: str
    organization_name: str | None = None
    phone_country_code: str | None = Field(default=None, description="E.g. +351")
    phone_number: str | None = None


# --- User ---
class UpdateUserRequest(BaseModel):
    name: str | None = None
    phone_country_code: str | None = Field(default=None, description="E.g. +351")
    phone_number: str | None = None


class PhoneResponse(BaseModel):
    country_code: str
    number: str


class UserResponse(BaseModel):
    id: UUID
    supabase_user_id: str
    email: str
    name: str
    phone: PhoneResponse | None
    organization_id: UUID | None
    created_at: datetime
    updated_at: datetime


# --- Organization ---
class UpdateOrganizationRequest(BaseModel):
    name: str | None = None
    nif: str | None = Field(default=None, description="Tax identification number (NIF)")
    address: str | None = None


class OrganizationResponse(BaseModel):
    id: UUID
    created_by: UUID
    name: str | None
    nif: str | None
    address: str | None
    created_at: datetime
    updated_at: datetime


# --- Subscription ---
class CreateSubscriptionRequest(BaseModel):
    plan: SubscriptionPlan
    type: SubscriptionType
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE
    stripe_subscription_id: str | None = None
    stripe_price_id: str | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None


class UpdateSubscriptionRequest(BaseModel):
    status: SubscriptionStatus | None = None
    stripe_subscription_id: str | None = None
    stripe_price_id: str | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None


class SubscriptionResponse(BaseModel):
    id: UUID
    organization_id: UUID
    plan: SubscriptionPlan
    type: SubscriptionType
    status: SubscriptionStatus
    stripe_subscription_id: str | None
    stripe_price_id: str | None
    current_period_start: datetime | None
    current_period_end: datetime | None
    created_at: datetime
    updated_at: datetime


class PlanResponse(BaseModel):
    name: str
    label: str


# --- Notification ---
class MarkNotificationsReadRequest(BaseModel):
    notification_ids: list[UUID]


class CreateNotificationRequest(BaseModel):
    user_id: UUID
    title: str
    message: str
    channel: str = "in_app"


class NotificationResponse(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    message: str
    status: NotificationStatus
    channel: str
    created_at: datetime
    read_at: datetime | None


# --- Email ---
class SendEmailRequest(BaseModel):
    to: str = Field(description="Recipient email address")
    subject: str
    html: str = Field(description="HTML body content")
    from_email: str = "noreply@predileto.pt"


# --- Membership ---
class InviteMemberRequest(BaseModel):
    email: str
    role: MembershipRole


class UpdateMemberRoleRequest(BaseModel):
    role: MembershipRole


class MembershipResponse(BaseModel):
    id: UUID
    user_id: UUID
    organization_id: UUID
    role: MembershipRole
    created_at: datetime
    updated_at: datetime


# --- Invitation ---
class InvitationResponse(BaseModel):
    id: UUID
    email: str
    role: MembershipRole
    status: InvitationStatus
    invited_by: UUID
    organization_id: UUID
    expires_at: datetime
    created_at: datetime


# --- User with organization ---
class UserWithOrganizationResponse(BaseModel):
    user: UserResponse
    organization: OrganizationResponse | None
    role: MembershipRole | None = None
