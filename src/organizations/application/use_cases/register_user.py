from datetime import datetime, timezone
from uuid import uuid4

import structlog

from customers.application.ports.repositories.invitation_repository import (
    InvitationRepository,
)
from customers.application.ports.repositories.membership_repository import (
    MembershipRepository,
)
from customers.application.ports.repositories.organization_repository import (
    OrganizationRepository,
)
from customers.application.ports.repositories.subscription_repository import (
    SubscriptionRepository,
)
from customers.application.ports.repositories.user_repository import UserRepository
from customers.domain.exceptions import UserAlreadyExistsError
from customers.domain.models.invitation import InvitationStatus
from customers.domain.models.membership import Membership, MembershipRole
from customers.domain.models.organization import Organization
from customers.domain.models.subscription import (
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
    SubscriptionType,
)
from customers.domain.models.user import User
from customers.domain.models.value_objects import PhoneNumber

log = structlog.get_logger()


class RegisterUser:
    def __init__(
        self,
        user_repo: UserRepository,
        organization_repo: OrganizationRepository,
        subscription_repo: SubscriptionRepository,
        membership_repo: MembershipRepository,
        invitation_repo: InvitationRepository,
    ) -> None:
        self.user_repo = user_repo
        self.organization_repo = organization_repo
        self.subscription_repo = subscription_repo
        self.membership_repo = membership_repo
        self.invitation_repo = invitation_repo

    async def execute(
        self,
        *,
        supabase_user_id: str,
        email: str,
        name: str,
        organization_name: str | None = None,
        phone: PhoneNumber | None = None,
        google_metadata: dict | None = None,
    ) -> User:
        existing = await self.user_repo.get_by_supabase_id(supabase_user_id)
        if existing:
            raise UserAlreadyExistsError(email)

        now = datetime.now(timezone.utc)

        # Check for pending invitation
        invitation = await self.invitation_repo.get_pending_by_email(email)

        if invitation:
            # Invited user — join existing organization
            organization_id = invitation.organization_id
            role = invitation.role

            # Mark invitation as accepted
            invitation.status = InvitationStatus.ACCEPTED
            await self.invitation_repo.update(invitation)
        else:
            # New user — create organization
            organization = Organization(
                id=uuid4(),
                created_by=uuid4(),
                name=organization_name,
                nif=None,
                address=None,
                created_at=now,
                updated_at=now,
            )
            organization = await self.organization_repo.save(organization)
            organization_id = organization.id
            role = MembershipRole.OWNER

            # Create freemium subscription for new org
            subscription = Subscription(
                id=uuid4(),
                organization_id=organization_id,
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

        user = User(
            id=uuid4(),
            supabase_user_id=supabase_user_id,
            email=email,
            name=name,
            phone=phone,
            organization_id=organization_id,
            google_metadata=google_metadata,
            created_at=now,
            updated_at=now,
        )
        user = await self.user_repo.save(user)

        # Create membership
        membership = Membership(
            id=uuid4(),
            user_id=user.id,
            organization_id=organization_id,
            role=role,
            created_at=now,
            updated_at=now,
        )
        await self.membership_repo.save(membership)

        log.info("user_registered", user_id=str(user.id), email=user.email)
        return user
