from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID


class SubscriptionPlan(str, Enum):
    FREEMIUM = "freemium"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class SubscriptionType(str, Enum):
    STRIPE = "stripe"
    MANUAL = "manual"
    DEPOSIT = "deposit"


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
    PAST_DUE = "past_due"
    TRIALING = "trialing"
    INACTIVE = "inactive"


@dataclass
class Subscription:
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

    def update(
        self,
        *,
        status: SubscriptionStatus | None = None,
        stripe_subscription_id: str | None = None,
        stripe_price_id: str | None = None,
        current_period_start: datetime | None = None,
        current_period_end: datetime | None = None,
    ) -> None:
        if status is not None:
            self.status = status
        if stripe_subscription_id is not None:
            self.stripe_subscription_id = stripe_subscription_id
        if stripe_price_id is not None:
            self.stripe_price_id = stripe_price_id
        if current_period_start is not None:
            self.current_period_start = current_period_start
        if current_period_end is not None:
            self.current_period_end = current_period_end
        self.updated_at = datetime.now(timezone.utc)
