import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from customer_management.adapters.inmemory.inmemory_event_bus import InMemoryEventBus
from customer_management.adapters.inmemory.inmemory_invitation_repo import (
    InMemoryInvitationRepository,
)
from customer_management.adapters.inmemory.inmemory_membership_repo import (
    InMemoryMembershipRepository,
)
from customer_management.adapters.inmemory.inmemory_organization_repo import (
    InMemoryOrganizationRepository,
)
from customer_management.adapters.inmemory.inmemory_subscription_repo import (
    InMemorySubscriptionRepository,
)
from customer_management.adapters.inmemory.inmemory_user_repo import InMemoryUserRepository
from customer_management.application.use_cases.register_user import RegisterUser
from customer_management.domain.models.invitation import Invitation, InvitationStatus
from customer_management.domain.models.membership import MembershipRole
from customer_management.domain.models.organization import Organization


@pytest.fixture
def register_use_case():
    user_repo = InMemoryUserRepository()
    organization_repo = InMemoryOrganizationRepository()
    subscription_repo = InMemorySubscriptionRepository()
    membership_repo = InMemoryMembershipRepository()
    invitation_repo = InMemoryInvitationRepository()
    event_bus = InMemoryEventBus()
    uc = RegisterUser(
        user_repo=user_repo,
        organization_repo=organization_repo,
        subscription_repo=subscription_repo,
        membership_repo=membership_repo,
        invitation_repo=invitation_repo,
        event_bus=event_bus,
    )
    return uc, user_repo, organization_repo, subscription_repo, membership_repo, invitation_repo


@pytest.mark.asyncio
async def test_register_new_user_creates_org_and_owner_membership(register_use_case):
    uc, user_repo, org_repo, sub_repo, membership_repo, _ = register_use_case

    user = await uc.execute(
        supabase_user_id="new-user-sub",
        email="new@test.com",
        name="New User",
        organization_name="New Org",
    )

    assert user.organization_id is not None
    memberships = await membership_repo.list_by_user(user.id)
    assert len(memberships) == 1
    assert memberships[0].role == MembershipRole.OWNER


@pytest.mark.asyncio
async def test_register_invited_user_joins_existing_org(register_use_case):
    uc, user_repo, org_repo, sub_repo, membership_repo, invitation_repo = register_use_case

    # Create existing org and invitation
    now = datetime.now(timezone.utc)
    org = Organization(
        id=uuid4(),
        created_by=uuid4(),
        name="Existing Org",
        nif="987654321",
        address="Existing Address",
        created_at=now,
        updated_at=now,
    )
    await org_repo.save(org)

    invitation = Invitation(
        id=uuid4(),
        organization_id=org.id,
        email="invited@test.com",
        role=MembershipRole.MEMBER,
        invited_by=uuid4(),
        token=secrets.token_urlsafe(32),
        status=InvitationStatus.PENDING,
        expires_at=now + timedelta(days=7),
        created_at=now,
    )
    await invitation_repo.save(invitation)

    # Register as invited user
    user = await uc.execute(
        supabase_user_id="invited-user-sub",
        email="invited@test.com",
        name="Invited User",
    )

    assert user.organization_id == org.id
    memberships = await membership_repo.list_by_user(user.id)
    assert len(memberships) == 1
    assert memberships[0].role == MembershipRole.MEMBER
    assert memberships[0].organization_id == org.id

    # Invitation should be accepted
    updated_invitation = await invitation_repo.get_by_id(invitation.id)
    assert updated_invitation.status == InvitationStatus.ACCEPTED


@pytest.mark.asyncio
async def test_register_without_org_fields_and_no_invitation_fails(register_use_case):
    uc, *_ = register_use_case

    with pytest.raises(ValueError, match="organization_name is required"):
        await uc.execute(
            supabase_user_id="fail-user-sub",
            email="fail@test.com",
            name="Fail User",
        )
