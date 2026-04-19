from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from organizations.adapters.database.models import (
    InvitationModel,
    InvitationStatusEnum,
    MembershipModel,
    NotificationModel,
    OrganizationModel,
    SubscriptionModel,
    UserModel,
)
from organizations.application.ports.repositories.invitation_repository import (
    InvitationRepository,
)
from organizations.application.ports.repositories.membership_repository import (
    MembershipRepository,
    MembershipWithOrgName,
)
from organizations.application.ports.repositories.notification_repository import (
    NotificationRepository,
)
from organizations.application.ports.repositories.organization_repository import (
    OrganizationRepository,
)
from organizations.application.ports.repositories.subscription_repository import (
    SubscriptionRepository,
)
from organizations.application.ports.repositories.user_repository import UserRepository
from organizations.domain.models.invitation import Invitation, InvitationStatus
from organizations.domain.models.membership import Membership, MembershipRole
from organizations.domain.models.notification import Notification, NotificationStatus
from organizations.domain.models.organization import Organization
from organizations.domain.models.subscription import (
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
    SubscriptionType,
)
from organizations.domain.models.user import User
from organizations.domain.models.value_objects import PhoneNumber


# ── Organization ────────────────────────────────────────────────────────────


class SqlAlchemyOrganizationRepository(OrganizationRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_domain(m: OrganizationModel) -> Organization:
        return Organization(
            id=UUID(m.id),
            created_by=UUID(m.created_by),
            name=m.name,
            nif=m.nif,
            address=m.address,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )

    @staticmethod
    def _to_model(o: Organization) -> OrganizationModel:
        return OrganizationModel(
            id=str(o.id),
            created_by=str(o.created_by),
            name=o.name,
            nif=o.nif,
            address=o.address,
        )

    async def get_by_id(self, organization_id: UUID) -> Organization | None:
        result = await self._session.execute(
            select(OrganizationModel).where(OrganizationModel.id == str(organization_id))
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def save(self, organization: Organization) -> Organization:
        model = self._to_model(organization)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)

    async def update(self, organization: Organization) -> Organization:
        result = await self._session.execute(
            select(OrganizationModel).where(OrganizationModel.id == str(organization.id))
        )
        model = result.scalar_one()
        model.created_by = str(organization.created_by)
        model.name = organization.name
        model.nif = organization.nif
        model.address = organization.address
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)


# ── User ─────────────────────────────────────────────────────────────────────


class SqlAlchemyUserRepository(UserRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_domain(m: UserModel) -> User:
        phone = None
        if m.phone_country_code and m.phone_number:
            phone = PhoneNumber(country_code=m.phone_country_code, number=m.phone_number)
        return User(
            id=UUID(m.id),
            supabase_user_id=m.supabase_user_id,
            email=m.email,
            name=m.name,
            phone=phone,
            organization_id=UUID(m.organization_id) if m.organization_id else None,
            google_metadata=m.google_metadata,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )

    @staticmethod
    def _to_model(u: User) -> UserModel:
        return UserModel(
            id=str(u.id),
            supabase_user_id=u.supabase_user_id,
            email=u.email,
            name=u.name,
            phone_country_code=u.phone.country_code if u.phone else None,
            phone_number=u.phone.number if u.phone else None,
            organization_id=str(u.organization_id) if u.organization_id else None,
            google_metadata=u.google_metadata,
        )

    async def get_by_id(self, user_id: UUID) -> User | None:
        result = await self._session.execute(select(UserModel).where(UserModel.id == str(user_id)))
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_supabase_id(self, supabase_user_id: str) -> User | None:
        result = await self._session.execute(
            select(UserModel).where(UserModel.supabase_user_id == supabase_user_id)
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(UserModel).where(UserModel.email == email))
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def save(self, user: User) -> User:
        model = self._to_model(user)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)

    async def update(self, user: User) -> User:
        result = await self._session.execute(select(UserModel).where(UserModel.id == str(user.id)))
        model = result.scalar_one()
        model.supabase_user_id = user.supabase_user_id
        model.email = user.email
        model.name = user.name
        model.phone_country_code = user.phone.country_code if user.phone else None
        model.phone_number = user.phone.number if user.phone else None
        model.organization_id = str(user.organization_id) if user.organization_id else None
        model.google_metadata = user.google_metadata
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)


# ── Subscription ─────────────────────────────────────────────────────────────


class SqlAlchemySubscriptionRepository(SubscriptionRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_domain(m: SubscriptionModel) -> Subscription:
        return Subscription(
            id=UUID(m.id),
            organization_id=UUID(m.organization_id),
            plan=SubscriptionPlan(m.plan.value),
            type=SubscriptionType(m.type.value),
            status=SubscriptionStatus(m.status.value),
            stripe_subscription_id=m.stripe_subscription_id,
            stripe_price_id=m.stripe_price_id,
            current_period_start=m.current_period_start,
            current_period_end=m.current_period_end,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )

    @staticmethod
    def _strip_tz(dt: datetime | None) -> datetime | None:
        """Strip timezone info for TIMESTAMP WITHOUT TIME ZONE columns."""
        return dt.replace(tzinfo=None) if dt and dt.tzinfo else dt

    @classmethod
    def _to_model(cls, s: Subscription) -> SubscriptionModel:
        return SubscriptionModel(
            id=str(s.id),
            organization_id=str(s.organization_id),
            plan=s.plan.value,
            type=s.type.value,
            status=s.status.value,
            stripe_subscription_id=s.stripe_subscription_id,
            stripe_price_id=s.stripe_price_id,
            current_period_start=cls._strip_tz(s.current_period_start),
            current_period_end=cls._strip_tz(s.current_period_end),
        )

    async def get_by_id(self, subscription_id: UUID) -> Subscription | None:
        result = await self._session.execute(
            select(SubscriptionModel).where(SubscriptionModel.id == str(subscription_id))
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_organization_id(self, organization_id: UUID) -> Subscription | None:
        result = await self._session.execute(
            select(SubscriptionModel)
            .where(SubscriptionModel.organization_id == str(organization_id))
            .order_by(SubscriptionModel.created_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def save(self, subscription: Subscription) -> Subscription:
        model = self._to_model(subscription)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)

    async def update(self, subscription: Subscription) -> Subscription:
        result = await self._session.execute(
            select(SubscriptionModel).where(SubscriptionModel.id == str(subscription.id))
        )
        model = result.scalar_one()
        model.organization_id = str(subscription.organization_id)
        model.plan = subscription.plan.value
        model.type = subscription.type.value
        model.status = subscription.status.value
        model.stripe_subscription_id = subscription.stripe_subscription_id
        model.stripe_price_id = subscription.stripe_price_id
        model.current_period_start = self._strip_tz(subscription.current_period_start)
        model.current_period_end = self._strip_tz(subscription.current_period_end)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)


# ── Notification ─────────────────────────────────────────────────────────────


class SqlAlchemyNotificationRepository(NotificationRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_domain(m: NotificationModel) -> Notification:
        return Notification(
            id=UUID(m.id),
            user_id=UUID(m.user_id),
            title=m.title,
            message=m.message,
            status=NotificationStatus(m.status.value),
            channel=m.channel,
            created_at=m.created_at,
            read_at=m.read_at,
        )

    @staticmethod
    def _to_model(n: Notification) -> NotificationModel:
        return NotificationModel(
            id=str(n.id),
            user_id=str(n.user_id),
            title=n.title,
            message=n.message,
            status=n.status.value,
            channel=n.channel,
        )

    async def get_by_id(self, notification_id: UUID) -> Notification | None:
        result = await self._session.execute(
            select(NotificationModel).where(NotificationModel.id == str(notification_id))
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def list_by_user_id(
        self, user_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> list[Notification]:
        result = await self._session.execute(
            select(NotificationModel)
            .where(NotificationModel.user_id == str(user_id))
            .order_by(NotificationModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [self._to_domain(row) for row in result.scalars().all()]

    async def save(self, notification: Notification) -> Notification:
        model = self._to_model(notification)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)

    async def mark_as_read(self, notification_ids: list[UUID], user_id: UUID) -> int:
        str_ids = [str(nid) for nid in notification_ids]
        now = datetime.now(timezone.utc)
        result = await self._session.execute(
            select(NotificationModel).where(
                NotificationModel.id.in_(str_ids),
                NotificationModel.user_id == str(user_id),
            )
        )
        rows = result.scalars().all()
        for row in rows:
            row.status = NotificationStatus.READ.value
            row.read_at = now
        await self._session.flush()
        return len(rows)


# ── Membership ──────────────────────────────────────────────────────────────


class SqlAlchemyMembershipRepository(MembershipRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_domain(m: MembershipModel) -> Membership:
        return Membership(
            id=UUID(m.id),
            user_id=UUID(m.user_id),
            organization_id=UUID(m.organization_id),
            role=MembershipRole(m.role.value),
            created_at=m.created_at,
            updated_at=m.updated_at,
        )

    @staticmethod
    def _to_model(membership: Membership) -> MembershipModel:
        return MembershipModel(
            id=str(membership.id),
            user_id=str(membership.user_id),
            organization_id=str(membership.organization_id),
            role=membership.role.value,
        )

    async def get_by_id(self, membership_id: UUID) -> Membership | None:
        result = await self._session.execute(
            select(MembershipModel).where(MembershipModel.id == str(membership_id))
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_user_and_organization(
        self, user_id: UUID, organization_id: UUID
    ) -> Membership | None:
        result = await self._session.execute(
            select(MembershipModel).where(
                MembershipModel.user_id == str(user_id),
                MembershipModel.organization_id == str(organization_id),
            )
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def list_by_organization(self, organization_id: UUID) -> list[Membership]:
        result = await self._session.execute(
            select(MembershipModel).where(MembershipModel.organization_id == str(organization_id))
        )
        return [self._to_domain(row) for row in result.scalars().all()]

    async def list_by_user(self, user_id: UUID) -> list[Membership]:
        result = await self._session.execute(
            select(MembershipModel).where(MembershipModel.user_id == str(user_id))
        )
        return [self._to_domain(row) for row in result.scalars().all()]

    async def list_by_user_id_with_org_names(
        self, user_id: UUID
    ) -> list[MembershipWithOrgName]:
        # Single JOIN, avoids N+1 when /me renders the membership list.
        stmt = (
            select(MembershipModel, OrganizationModel.name)
            .join(OrganizationModel, MembershipModel.organization_id == OrganizationModel.id)
            .where(MembershipModel.user_id == str(user_id))
        )
        result = await self._session.execute(stmt)
        out: list[MembershipWithOrgName] = []
        for m, org_name in result.all():
            out.append(
                MembershipWithOrgName(
                    id=UUID(m.id),
                    user_id=UUID(m.user_id),
                    organization_id=UUID(m.organization_id),
                    role=MembershipRole(m.role),
                    organization_name=org_name,
                    created_at=m.created_at,
                    updated_at=m.updated_at,
                )
            )
        return out

    async def save(self, membership: Membership) -> Membership:
        model = self._to_model(membership)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)

    async def update(self, membership: Membership) -> Membership:
        result = await self._session.execute(
            select(MembershipModel).where(MembershipModel.id == str(membership.id))
        )
        model = result.scalar_one()
        model.role = membership.role.value
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)

    async def delete(self, membership_id: UUID) -> None:
        result = await self._session.execute(
            select(MembershipModel).where(MembershipModel.id == str(membership_id))
        )
        model = result.scalar_one_or_none()
        if model:
            await self._session.delete(model)
            await self._session.flush()


# ── Invitation ──────────────────────────────────────────────────────────────


class SqlAlchemyInvitationRepository(InvitationRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_domain(m: InvitationModel) -> Invitation:
        return Invitation(
            id=UUID(m.id),
            organization_id=UUID(m.organization_id),
            email=m.email,
            role=MembershipRole(m.role.value),
            invited_by=UUID(m.invited_by),
            token=m.token,
            status=InvitationStatus(m.status.value),
            expires_at=m.expires_at,
            created_at=m.created_at,
        )

    @staticmethod
    def _to_model(invitation: Invitation) -> InvitationModel:
        return InvitationModel(
            id=str(invitation.id),
            organization_id=str(invitation.organization_id),
            email=invitation.email,
            role=invitation.role.value,
            invited_by=str(invitation.invited_by),
            token=invitation.token,
            status=invitation.status.value,
            expires_at=invitation.expires_at,
        )

    async def get_by_id(self, invitation_id: UUID) -> Invitation | None:
        result = await self._session.execute(
            select(InvitationModel).where(InvitationModel.id == str(invitation_id))
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_pending_by_email(self, email: str) -> Invitation | None:
        result = await self._session.execute(
            select(InvitationModel)
            .where(
                InvitationModel.email == email,
                InvitationModel.status == InvitationStatusEnum.PENDING,
            )
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_pending_by_email_and_organization(
        self, email: str, organization_id: UUID
    ) -> Invitation | None:
        result = await self._session.execute(
            select(InvitationModel).where(
                InvitationModel.email == email,
                InvitationModel.organization_id == str(organization_id),
                InvitationModel.status == InvitationStatusEnum.PENDING,
            )
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def list_by_organization(self, organization_id: UUID) -> list[Invitation]:
        result = await self._session.execute(
            select(InvitationModel).where(InvitationModel.organization_id == str(organization_id))
        )
        return [self._to_domain(row) for row in result.scalars().all()]

    async def save(self, invitation: Invitation) -> Invitation:
        model = self._to_model(invitation)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)

    async def update(self, invitation: Invitation) -> Invitation:
        result = await self._session.execute(
            select(InvitationModel).where(InvitationModel.id == str(invitation.id))
        )
        model = result.scalar_one()
        model.status = invitation.status.value
        model.role = invitation.role.value
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)
