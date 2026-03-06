from dataclasses import dataclass
from datetime import datetime
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
