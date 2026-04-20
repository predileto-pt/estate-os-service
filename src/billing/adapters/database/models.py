import enum
from datetime import datetime

from sqlalchemy import (
    Enum,
    ForeignKey,
    Index,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.database.models import Base


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


class SubscriptionModel(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=False
    )
    plan: Mapped[SubscriptionPlan] = mapped_column(
        Enum(
            SubscriptionPlan,
            name="subscription_plan",
            values_callable=lambda e: [x.value for x in e],
        ),
        nullable=False,
        server_default="freemium",
    )
    type: Mapped[SubscriptionType] = mapped_column(
        Enum(
            SubscriptionType,
            name="subscription_type",
            values_callable=lambda e: [x.value for x in e],
        ),
        nullable=False,
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(
            SubscriptionStatus,
            name="subscription_status",
            values_callable=lambda e: [x.value for x in e],
        ),
        nullable=False,
        server_default="active",
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(Text)
    stripe_subscription_id: Mapped[str | None] = mapped_column(Text)
    stripe_price_id: Mapped[str | None] = mapped_column(Text)
    current_period_start: Mapped[datetime | None] = mapped_column()
    current_period_end: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    __table_args__ = (
        Index(
            "idx_subscriptions_stripe_customer_id",
            "stripe_customer_id",
            postgresql_where=text("stripe_customer_id IS NOT NULL"),
        ),
    )


class StripeWebhookEventModel(Base):
    """Idempotency table for Stripe webhook events.

    Every processed Stripe event is recorded here; the webhook handler
    checks membership before applying side effects, so retries / replays
    are no-ops. Stripe retries any non-2xx response, so this table also
    guards against double-apply on transient handler failures.
    """

    __tablename__ = "stripe_webhook_events"

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
