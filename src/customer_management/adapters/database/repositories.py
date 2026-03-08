from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from customer_management.adapters.database.models import (
    CompanyModel,
    NotificationModel,
    SubscriptionModel,
    UserModel,
)
from customer_management.application.ports.repositories.company_repository import CompanyRepository
from customer_management.application.ports.repositories.notification_repository import NotificationRepository
from customer_management.application.ports.repositories.subscription_repository import SubscriptionRepository
from customer_management.application.ports.repositories.user_repository import UserRepository
from customer_management.domain.models.company import Company
from customer_management.domain.models.notification import Notification, NotificationStatus
from customer_management.domain.models.subscription import (
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
    SubscriptionType,
)
from customer_management.domain.models.user import User
from customer_management.domain.models.value_objects import PhoneNumber


# ── Company ──────────────────────────────────────────────────────────────────


class SqlAlchemyCompanyRepository(CompanyRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_domain(m: CompanyModel) -> Company:
        return Company(
            id=UUID(m.id),
            user_id=UUID(m.user_id),
            name=m.name,
            nif=m.nif,
            address=m.address,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )

    @staticmethod
    def _to_model(c: Company) -> CompanyModel:
        return CompanyModel(
            id=str(c.id),
            user_id=str(c.user_id),
            name=c.name,
            nif=c.nif,
            address=c.address,
        )

    async def get_by_id(self, company_id: UUID) -> Company | None:
        result = await self._session.execute(
            select(CompanyModel).where(CompanyModel.id == str(company_id))
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def save(self, company: Company) -> Company:
        model = self._to_model(company)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)

    async def update(self, company: Company) -> Company:
        result = await self._session.execute(
            select(CompanyModel).where(CompanyModel.id == str(company.id))
        )
        model = result.scalar_one()
        model.user_id = str(company.user_id)
        model.name = company.name
        model.nif = company.nif
        model.address = company.address
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
            company_id=UUID(m.company_id),
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
            company_id=str(u.company_id),
            google_metadata=u.google_metadata,
        )

    async def get_by_id(self, user_id: UUID) -> User | None:
        result = await self._session.execute(
            select(UserModel).where(UserModel.id == str(user_id))
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_supabase_id(self, supabase_user_id: str) -> User | None:
        result = await self._session.execute(
            select(UserModel).where(UserModel.supabase_user_id == supabase_user_id)
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(
            select(UserModel).where(UserModel.email == email)
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def save(self, user: User) -> User:
        model = self._to_model(user)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)

    async def update(self, user: User) -> User:
        result = await self._session.execute(
            select(UserModel).where(UserModel.id == str(user.id))
        )
        model = result.scalar_one()
        model.supabase_user_id = user.supabase_user_id
        model.email = user.email
        model.name = user.name
        model.phone_country_code = user.phone.country_code if user.phone else None
        model.phone_number = user.phone.number if user.phone else None
        model.company_id = str(user.company_id)
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
            company_id=UUID(m.company_id),
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
    def _to_model(s: Subscription) -> SubscriptionModel:
        return SubscriptionModel(
            id=str(s.id),
            company_id=str(s.company_id),
            plan=s.plan.value,
            type=s.type.value,
            status=s.status.value,
            stripe_subscription_id=s.stripe_subscription_id,
            stripe_price_id=s.stripe_price_id,
            current_period_start=s.current_period_start,
            current_period_end=s.current_period_end,
        )

    async def get_by_id(self, subscription_id: UUID) -> Subscription | None:
        result = await self._session.execute(
            select(SubscriptionModel).where(SubscriptionModel.id == str(subscription_id))
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_company_id(self, company_id: UUID) -> Subscription | None:
        result = await self._session.execute(
            select(SubscriptionModel)
            .where(SubscriptionModel.company_id == str(company_id))
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
        model.company_id = str(subscription.company_id)
        model.plan = subscription.plan.value
        model.type = subscription.type.value
        model.status = subscription.status.value
        model.stripe_subscription_id = subscription.stripe_subscription_id
        model.stripe_price_id = subscription.stripe_price_id
        model.current_period_start = subscription.current_period_start
        model.current_period_end = subscription.current_period_end
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
