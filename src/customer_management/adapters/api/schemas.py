from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from customer_management.domain.models.notification import NotificationStatus
from customer_management.domain.models.subscription import (
    SubscriptionPlan,
    SubscriptionStatus,
    SubscriptionType,
)


# --- Auth ---
class RegisterRequest(BaseModel):
    name: str
    email: str
    company_name: str
    nif: str = Field(description="Tax identification number (NIF)")
    address: str = Field(description="Company address")
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
    company_id: UUID
    created_at: datetime
    updated_at: datetime


# --- Company ---
class UpdateCompanyRequest(BaseModel):
    name: str | None = None
    nif: str | None = Field(default=None, description="Tax identification number (NIF)")
    address: str | None = None


class CompanyResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    nif: str
    address: str
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
    company_id: UUID
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


# --- User with company ---
class UserWithCompanyResponse(BaseModel):
    user: UserResponse
    company: CompanyResponse | None
