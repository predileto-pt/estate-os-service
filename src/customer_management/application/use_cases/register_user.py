from datetime import datetime, timezone
from uuid import uuid4

import structlog

from customer_management.application.ports.event_bus import EventBus
from customer_management.application.ports.repositories.invitation_repository import (
    InvitationRepository,
)
from customer_management.application.ports.repositories.membership_repository import (
    MembershipRepository,
)
from customer_management.application.ports.repositories.organization_repository import (
    OrganizationRepository,
)
from customer_management.application.ports.repositories.subscription_repository import (
    SubscriptionRepository,
)
from customer_management.application.ports.repositories.user_repository import UserRepository
from customer_management.domain.events import MemberJoined, UserRegistered
from customer_management.domain.exceptions import UserAlreadyExistsError
from customer_management.domain.models.invitation import InvitationStatus
from customer_management.domain.models.membership import Membership, MembershipRole
from customer_management.domain.models.organization import Organization
from customer_management.domain.models.subscription import (
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
    SubscriptionType,
)
from customer_management.domain.models.user import User
from customer_management.domain.models.value_objects import PhoneNumber

log = structlog.get_logger()


class RegisterUser:
    def __init__(
        self,
        user_repo: UserRepository,
        organization_repo: OrganizationRepository,
        subscription_repo: SubscriptionRepository,
        membership_repo: MembershipRepository,
        invitation_repo: InvitationRepository,
        event_bus: EventBus,
    ) -> None:
        self.user_repo = user_repo
        self.organization_repo = organization_repo
        self.subscription_repo = subscription_repo
        self.membership_repo = membership_repo
        self.invitation_repo = invitation_repo
        self.event_bus = event_bus

    async def execute(
        self,
        *,
        supabase_user_id: str,
        email: str,
        name: str,
        organization_name: str | None = None,
        nif: str | None = None,
        address: str | None = None,
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
            if not organization_name or not nif or not address:
                raise ValueError(
                    "organization_name, nif, and address are required for new registrations"
                )

            organization = Organization(
                id=uuid4(),
                created_by=uuid4(),
                name=organization_name,
                nif=nif,
                address=address,
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

        await self.event_bus.publish(
            UserRegistered(user_id=user.id, email=user.email, organization_id=organization_id)
        )
        await self.event_bus.publish(
            MemberJoined(
                membership_id=membership.id,
                user_id=user.id,
                organization_id=organization_id,
                role=role.value,
            )
        )

        log.info("user_registered", user_id=str(user.id), email=user.email)
        return user
