from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4


@dataclass(frozen=True)
class DomainEvent:
    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class UserRegistered(DomainEvent):
    user_id: UUID = field(default_factory=uuid4)
    email: str = ""
    organization_id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True)
class SubscriptionCreated(DomainEvent):
    subscription_id: UUID = field(default_factory=uuid4)
    organization_id: UUID = field(default_factory=uuid4)
    plan: str = ""


@dataclass(frozen=True)
class SubscriptionUpdated(DomainEvent):
    subscription_id: UUID = field(default_factory=uuid4)
    old_status: str = ""
    new_status: str = ""


@dataclass(frozen=True)
class NotificationSent(DomainEvent):
    notification_id: UUID = field(default_factory=uuid4)
    user_id: UUID = field(default_factory=uuid4)
    channel: str = ""


@dataclass(frozen=True)
class MemberInvited(DomainEvent):
    invitation_id: UUID = field(default_factory=uuid4)
    organization_id: UUID = field(default_factory=uuid4)
    email: str = ""
    role: str = ""


@dataclass(frozen=True)
class MemberJoined(DomainEvent):
    membership_id: UUID = field(default_factory=uuid4)
    user_id: UUID = field(default_factory=uuid4)
    organization_id: UUID = field(default_factory=uuid4)
    role: str = ""


@dataclass(frozen=True)
class MemberRemoved(DomainEvent):
    membership_id: UUID = field(default_factory=uuid4)
    user_id: UUID = field(default_factory=uuid4)
    organization_id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True)
class MemberRoleChanged(DomainEvent):
    membership_id: UUID = field(default_factory=uuid4)
    user_id: UUID = field(default_factory=uuid4)
    organization_id: UUID = field(default_factory=uuid4)
    old_role: str = ""
    new_role: str = ""
