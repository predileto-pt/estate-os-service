from datetime import datetime, timezone
from uuid import UUID, uuid4

import structlog

from core_api.application.ports.event_bus import EventBus
from core_api.application.ports.repositories.company_repository import CompanyRepository
from core_api.application.ports.repositories.subscription_repository import SubscriptionRepository
from core_api.application.ports.repositories.user_repository import UserRepository
from core_api.domain.events import UserRegistered
from core_api.domain.exceptions import UserAlreadyExistsError
from core_api.domain.models.company import Company
from core_api.domain.models.subscription import (
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
    SubscriptionType,
)
from core_api.domain.models.user import User
from core_api.domain.models.value_objects import PhoneNumber

log = structlog.get_logger()


class RegisterUser:
    def __init__(
        self,
        user_repo: UserRepository,
        company_repo: CompanyRepository,
        subscription_repo: SubscriptionRepository,
        event_bus: EventBus,
    ) -> None:
        self.user_repo = user_repo
        self.company_repo = company_repo
        self.subscription_repo = subscription_repo
        self.event_bus = event_bus

    async def execute(
        self,
        *,
        supabase_user_id: str,
        email: str,
        name: str,
        company_name: str,
        nif: str,
        address: str,
        phone: PhoneNumber | None = None,
        google_metadata: dict | None = None,
    ) -> User:
        existing = await self.user_repo.get_by_supabase_id(supabase_user_id)
        if existing:
            raise UserAlreadyExistsError(email)

        now = datetime.now(timezone.utc)

        company = Company(
            id=uuid4(),
            user_id=UUID(supabase_user_id),
            name=company_name,
            nif=nif,
            address=address,
            created_at=now,
            updated_at=now,
        )
        company = await self.company_repo.save(company)

        user = User(
            id=uuid4(),
            supabase_user_id=supabase_user_id,
            email=email,
            name=name,
            phone=phone,
            company_id=company.id,
            google_metadata=google_metadata,
            created_at=now,
            updated_at=now,
        )
        user = await self.user_repo.save(user)

        subscription = Subscription(
            id=uuid4(),
            company_id=company.id,
            plan=SubscriptionPlan.FREEMIUM,
            type=SubscriptionType.MANUAL,
            status=SubscriptionStatus.ACTIVE,
            stripe_subscription_id=None,
            stripe_price_id=None,
            current_period_start=now,
            current_period_end=None,
            created_at=now,
            updated_at=now,
        )
        await self.subscription_repo.save(subscription)

        await self.event_bus.publish(
            UserRegistered(user_id=user.id, email=user.email, company_id=company.id)
        )

        log.info("user_registered", user_id=str(user.id), email=user.email)
        return user
