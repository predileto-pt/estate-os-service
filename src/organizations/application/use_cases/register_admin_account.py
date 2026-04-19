"""Compound admin-account registration.

Orchestrates the three-step flow documented in the identity-split spec:

1. Call `identity.register_user` via the injected `RegisterUserPort`
   callable. Idempotent on `supabase_user_id`; returns the existing User
   on retry.
2. Duplicate-account check: if the user already has ANY memberships,
   raise `AdminAccountAlreadyExistsError` (mapped to HTTP 409 in the
   route handler). Rules out double-submits and portal-user-promotes.
3. Create Organization + OwnerMembership + Subscription in a single
   organizations-local transaction. If this raises, the User from step 1
   is orphaned but the request is safely retryable — on retry, step 1
   no-ops and step 3 reruns.

Cross-context dependency is one-way: this use case calls identity via
the `RegisterUserPort` Protocol. Identity never imports from organizations.
"""

from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

import structlog

from identity.domain.models.user import User
from identity.domain.value_objects import PhoneNumber
from organizations.application.ports.repositories.invitation_repository import (
    InvitationRepository,
)
from organizations.application.ports.repositories.membership_repository import (
    MembershipRepository,
)
from organizations.application.ports.repositories.organization_repository import (
    OrganizationRepository,
)
from organizations.application.ports.repositories.subscription_repository import (
    SubscriptionRepository,
)
from organizations.domain.exceptions import DomainError
from organizations.domain.models.invitation import InvitationStatus
from organizations.domain.models.membership import Membership, MembershipRole
from organizations.domain.models.organization import Organization
from organizations.domain.models.subscription import (
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
    SubscriptionType,
)

log = structlog.get_logger()


class AdminAccountAlreadyExistsError(DomainError):
    """The Supabase user already has one or more memberships.

    Mapped to HTTP 409 in `admin_auth.py`. Signals that the caller should
    log in instead of re-registering.
    """


class RegisterUserPort(Protocol):
    async def __call__(
        self,
        *,
        supabase_user_id: str,
        email: str,
        name: str,
        phone: PhoneNumber | None = None,
        google_metadata: dict | None = None,
    ) -> User: ...


class RegisterAdminAccount:
    def __init__(
        self,
        register_user_port: RegisterUserPort,
        organization_repo: OrganizationRepository,
        membership_repo: MembershipRepository,
        subscription_repo: SubscriptionRepository,
        invitation_repo: InvitationRepository,
    ) -> None:
        self.register_user_port = register_user_port
        self.organization_repo = organization_repo
        self.membership_repo = membership_repo
        self.subscription_repo = subscription_repo
        self.invitation_repo = invitation_repo

    async def execute(
        self,
        *,
        supabase_user_id: str,
        email: str,
        name: str,
        phone: PhoneNumber | None = None,
        organization_name: str | None = None,
        google_metadata: dict | None = None,
    ) -> tuple[User, Organization, Membership, Subscription]:
        # Step 1 — identity-local, idempotent.
        user = await self.register_user_port(
            supabase_user_id=supabase_user_id,
            email=email,
            name=name,
            phone=phone,
            google_metadata=google_metadata,
        )

        # Step 2 — duplicate-account check.
        existing_memberships = await self.membership_repo.list_by_user(user.id)
        if existing_memberships:
            log.info(
                "register_admin_account.duplicate",
                user_id=str(user.id),
                memberships=len(existing_memberships),
            )
            raise AdminAccountAlreadyExistsError("Admin account already exists")

        # Step 3 — organizations-local tx: Org + OwnerMembership + Subscription.
        now = datetime.now(timezone.utc)
        role = MembershipRole.OWNER

        # Honour pending email invitation if one exists: join the existing
        # org instead of creating a new one.
        invitation = await self.invitation_repo.get_pending_by_email(email)
        if invitation:
            organization_id = invitation.organization_id
            role = invitation.role
            organization = await self.organization_repo.get_by_id(organization_id)
            invitation.status = InvitationStatus.ACCEPTED
            await self.invitation_repo.update(invitation)
            subscription = None  # Joining existing org — no new sub.
        else:
            organization = Organization(
                id=uuid4(),
                created_by=user.id,
                name=organization_name,
                nif=None,
                address=None,
                created_at=now,
                updated_at=now,
            )
            organization = await self.organization_repo.save(organization)
            organization_id = organization.id

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
            subscription = await self.subscription_repo.save(subscription)

        membership = Membership(
            id=uuid4(),
            user_id=user.id,
            organization_id=organization_id,
            role=role,
            created_at=now,
            updated_at=now,
        )
        membership = await self.membership_repo.save(membership)

        log.info(
            "register_admin_account.completed",
            user_id=str(user.id),
            organization_id=str(organization_id),
            role=role.value,
        )
        return user, organization, membership, subscription
