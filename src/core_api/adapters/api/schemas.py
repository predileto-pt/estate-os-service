from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


# --- Auth ---
class RegisterRequest(BaseModel):
    name: str
    email: str
    company_name: str
    tax_id_number: str
    address_street: str
    address_parish: str | None = None
    address_municipality: str | None = None
    address_district: str | None = None
    address_postal_code: str | None = None
    address_country: str = "PT"
    phone_country_code: str | None = None
    phone_number: str | None = None


# --- User ---
class UpdateUserRequest(BaseModel):
    name: str | None = None
    phone_country_code: str | None = None
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
    tax_id_number: str | None = None
    address_street: str | None = None
    address_parish: str | None = None
    address_municipality: str | None = None
    address_district: str | None = None
    address_postal_code: str | None = None
    address_country: str | None = None


class AddressResponse(BaseModel):
    street: str
    parish: str | None
    municipality: str | None
    district: str | None
    postal_code: str | None
    country: str


class CompanyResponse(BaseModel):
    id: UUID
    name: str
    tax_id_number: str
    address: AddressResponse
    stripe_customer_id: str | None
    created_at: datetime
    updated_at: datetime


# --- Subscription ---
class CreateSubscriptionRequest(BaseModel):
    plan: str
    type: str
    status: str = "active"
    stripe_subscription_id: str | None = None
    stripe_price_id: str | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None


class UpdateSubscriptionRequest(BaseModel):
    status: str | None = None
    stripe_subscription_id: str | None = None
    stripe_price_id: str | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None


class SubscriptionResponse(BaseModel):
    id: UUID
    company_id: UUID
    plan: str
    type: str
    status: str
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
    status: str
    channel: str
    created_at: datetime
    read_at: datetime | None


# --- Email ---
class SendEmailRequest(BaseModel):
    to: str
    subject: str
    html: str
    from_email: str = "noreply@predileto.pt"


# --- User with company ---
class UserWithCompanyResponse(BaseModel):
    user: UserResponse
    company: CompanyResponse | None
