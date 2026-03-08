import enum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from datetime import datetime


class Base(DeclarativeBase):
    pass


# ── Enums ────────────────────────────────────────────────────────────────────


class ApplicantStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class SubscriptionPlan(str, enum.Enum):
    FREEMIUM = "freemium"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class SubscriptionType(str, enum.Enum):
    STRIPE = "stripe"
    MANUAL = "manual"
    DEPOSIT = "deposit"


class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
    PAST_DUE = "past_due"
    TRIALING = "trialing"
    INACTIVE = "inactive"


class IntakeFormRequestStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    EXPIRED = "expired"


class NotificationStatus(str, enum.Enum):
    UNREAD = "unread"
    READ = "read"


# ── Models ───────────────────────────────────────────────────────────────────


class ApplicantModel(Base):
    __tablename__ = "applicants"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()")
    )
    property_id: Mapped[str] = mapped_column(Text, nullable=False)
    property_title: Mapped[str] = mapped_column(Text, nullable=False)
    visitor_name: Mapped[str] = mapped_column(Text, nullable=False)
    visitor_email: Mapped[str] = mapped_column(Text, nullable=False)
    visitor_phone: Mapped[str | None] = mapped_column(Text)
    has_id_document: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    has_proof_of_income: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ApplicantStatus] = mapped_column(
        Enum(ApplicantStatus, name="applicant_status", values_callable=lambda e: [x.value for x in e]),
        nullable=False,
        server_default="pending",
    )
    visitor_nif: Mapped[str | None] = mapped_column(Text)
    visitor_date_of_birth: Mapped[datetime | None] = mapped_column(Date)
    property_price: Mapped[float | None] = mapped_column(Float)
    property_address: Mapped[str | None] = mapped_column(Text)
    justification: Mapped[str | None] = mapped_column(Text)
    income_records: Mapped[dict | None] = mapped_column(JSONB)
    form_request_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    screening_applicant_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    agency_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column()

    __table_args__ = (
        Index("idx_applicants_form_request_id", "form_request_id"),
    )


class CompanyModel(Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    nif: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()")
    )
    supabase_user_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    phone_country_code: Mapped[str | None] = mapped_column(Text)
    phone_number: Mapped[str | None] = mapped_column(Text)
    company_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("companies.id"), nullable=False
    )
    google_metadata: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("supabase_user_id", name="uq_users_supabase_user_id"),
        UniqueConstraint("email", name="uq_users_email"),
    )


class SubscriptionModel(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()")
    )
    company_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("companies.id"), nullable=False
    )
    plan: Mapped[SubscriptionPlan] = mapped_column(
        Enum(SubscriptionPlan, name="subscription_plan", values_callable=lambda e: [x.value for x in e]),
        nullable=False,
        server_default="freemium",
    )
    type: Mapped[SubscriptionType] = mapped_column(
        Enum(SubscriptionType, name="subscription_type", values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, name="subscription_status", values_callable=lambda e: [x.value for x in e]),
        nullable=False,
        server_default="active",
    )
    stripe_subscription_id: Mapped[str | None] = mapped_column(Text)
    stripe_price_id: Mapped[str | None] = mapped_column(Text)
    current_period_start: Mapped[datetime | None] = mapped_column()
    current_period_end: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())


class NotificationModel(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus, name="notification_status", values_callable=lambda e: [x.value for x in e]),
        nullable=False,
        server_default="unread",
    )
    channel: Mapped[str] = mapped_column(Text, nullable=False, server_default="in_app")
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("idx_notifications_user_status", "user_id", "status"),
    )


class IntakeFormRequestModel(Base):
    __tablename__ = "intake_form_requests"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()")
    )
    agency_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    applicant_name: Mapped[str] = mapped_column(Text, nullable=False)
    applicant_email: Mapped[str] = mapped_column(Text, nullable=False)
    applicant_phone: Mapped[str | None] = mapped_column(Text)
    property_id: Mapped[str] = mapped_column(Text, nullable=False)
    property_title: Mapped[str | None] = mapped_column(Text)
    property_price: Mapped[float | None] = mapped_column(Float)
    property_address: Mapped[str | None] = mapped_column(Text)
    status: Mapped[IntakeFormRequestStatus] = mapped_column(
        Enum(
            IntakeFormRequestStatus,
            name="intake_form_request_status",
            values_callable=lambda e: [x.value for x in e],
        ),
        nullable=False,
        server_default="pending",
    )
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
