from datetime import datetime, timezone
from uuid import uuid4

import pytest

from customer_management.adapters.inmemory.inmemory_event_bus import InMemoryEventBus
from customer_management.adapters.inmemory.inmemory_invitation_repo import (
    InMemoryInvitationRepository,
)
from customer_management.adapters.inmemory.inmemory_membership_repo import (
    InMemoryMembershipRepository,
)
from customer_management.adapters.inmemory.inmemory_user_repo import InMemoryUserRepository
from customer_management.application.use_cases.invite_member import InviteMember
from customer_management.domain.exceptions import (
    InsufficientPermissionError,
    MembershipAlreadyExistsError,
)
from customer_management.domain.models.membership import Membership, MembershipRole
from customer_management.domain.models.user import User


@pytest.fixture
def invite_use_case():
    invitation_repo = InMemoryInvitationRepository()
    membership_repo = InMemoryMembershipRepository()
    user_repo = InMemoryUserRepository()
    event_bus = InMemoryEventBus()
    return (
        InviteMember(
            invitation_repo=invitation_repo,
            membership_repo=membership_repo,
            user_repo=user_repo,
            event_bus=event_bus,
        ),
        user_repo,
        membership_repo,
    )


async def _create_owner(user_repo, membership_repo):
    now = datetime.now(timezone.utc)
    org_id = uuid4()
    user = User(
        id=uuid4(),
        supabase_user_id="owner-sub",
        email="owner@test.com",
        name="Owner",
        phone=None,
        organization_id=org_id,
        google_metadata=None,
        created_at=now,
        updated_at=now,
    )
    await user_repo.save(user)
    membership = Membership(
        id=uuid4(),
        user_id=user.id,
        organization_id=org_id,
        role=MembershipRole.OWNER,
        created_at=now,
        updated_at=now,
    )
    await membership_repo.save(membership)
    return user, org_id


@pytest.mark.asyncio
async def test_invite_member_success(invite_use_case):
    uc, user_repo, membership_repo = invite_use_case
    owner, org_id = await _create_owner(user_repo, membership_repo)

    invitation = await uc.execute(
        supabase_user_id=owner.supabase_user_id,
        organization_id=org_id,
        email="invite@test.com",
        role=MembershipRole.MEMBER,
    )

    assert invitation.email == "invite@test.com"
    assert invitation.role == MembershipRole.MEMBER
    assert invitation.organization_id == org_id


@pytest.mark.asyncio
async def test_invite_member_as_member_fails(invite_use_case):
    uc, user_repo, membership_repo = invite_use_case
    now = datetime.now(timezone.utc)
    org_id = uuid4()

    member = User(
        id=uuid4(),
        supabase_user_id="member-sub",
        email="member@test.com",
        name="Member",
        phone=None,
        organization_id=org_id,
        google_metadata=None,
        created_at=now,
        updated_at=now,
    )
    await user_repo.save(member)
    await membership_repo.save(
        Membership(
            id=uuid4(),
            user_id=member.id,
            organization_id=org_id,
            role=MembershipRole.MEMBER,
            created_at=now,
            updated_at=now,
        )
    )

    with pytest.raises(InsufficientPermissionError):
        await uc.execute(
            supabase_user_id=member.supabase_user_id,
            organization_id=org_id,
            email="invite@test.com",
            role=MembershipRole.MEMBER,
        )


@pytest.mark.asyncio
async def test_invite_existing_member_fails(invite_use_case):
    uc, user_repo, membership_repo = invite_use_case
    owner, org_id = await _create_owner(user_repo, membership_repo)

    now = datetime.now(timezone.utc)
    existing = User(
        id=uuid4(),
        supabase_user_id="existing-sub",
        email="existing@test.com",
        name="Existing",
        phone=None,
        organization_id=org_id,
        google_metadata=None,
        created_at=now,
        updated_at=now,
    )
    await user_repo.save(existing)
    await membership_repo.save(
        Membership(
            id=uuid4(),
            user_id=existing.id,
            organization_id=org_id,
            role=MembershipRole.MEMBER,
            created_at=now,
            updated_at=now,
        )
    )

    with pytest.raises(MembershipAlreadyExistsError):
        await uc.execute(
            supabase_user_id=owner.supabase_user_id,
            organization_id=org_id,
            email="existing@test.com",
            role=MembershipRole.MEMBER,
        )
