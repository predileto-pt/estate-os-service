import enum

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from datetime import datetime

from shared.database.models import Base


# ── Enums ────────────────────────────────────────────────────────────────────


class NotificationStatus(str, enum.Enum):
    UNREAD = "unread"
    READ = "read"


class MembershipRoleEnum(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class InvitationStatusEnum(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    REVOKED = "revoked"


# ── Models ───────────────────────────────────────────────────────────────────


class OrganizationModel(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()")
    )
    created_by: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    nif: Mapped[str | None] = mapped_column(Text, nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone_country_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())


# UserModel moved to `identity.adapters.database.models`. Organizations'
# SupabaseUserRepository (prod PostgREST) stays; the SQLAlchemy test
# path uses identity's SqlAlchemyUserRepository since both contexts
# read the same `users` table row.


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
        Enum(
            NotificationStatus,
            name="notification_status",
            values_callable=lambda e: [x.value for x in e],
        ),
        nullable=False,
        server_default="unread",
    )
    channel: Mapped[str] = mapped_column(Text, nullable=False, server_default="in_app")
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("idx_notifications_user_status", "user_id", "status"),)


class MembershipModel(Base):
    __tablename__ = "memberships"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=False
    )
    organization_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=False
    )
    role: Mapped[MembershipRoleEnum] = mapped_column(
        Enum(
            MembershipRoleEnum,
            name="membership_role",
            values_callable=lambda e: [x.value for x in e],
            _create_events=False,
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "organization_id", name="uq_memberships_user_org"),
        Index("idx_memberships_organization_id", "organization_id"),
    )


class InvitationModel(Base):
    __tablename__ = "invitations"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=False
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[MembershipRoleEnum] = mapped_column(
        Enum(
            MembershipRoleEnum,
            name="membership_role",
            values_callable=lambda e: [x.value for x in e],
            _create_events=False,
        ),
        nullable=False,
    )
    invited_by: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=False
    )
    token: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    status: Mapped[InvitationStatusEnum] = mapped_column(
        Enum(
            InvitationStatusEnum,
            name="invitation_status",
            values_callable=lambda e: [x.value for x in e],
            _create_events=False,
        ),
        nullable=False,
        server_default="pending",
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    __table_args__ = (Index("idx_invitations_email_status", "email", "status"),)
