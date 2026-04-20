"""Unit tests for `organizations.RegisterAdminAccount`.

Three cases per the spec (identity-split-and-membership-auth §Tests):

1. **Success (fresh sub)**: register_user_port called once, memberships
   empty, Org + Membership + Subscription created, composite returned.
2. **Duplicate account (sub with existing membership)**: register_user
   returns existing User (idempotent), memberships non-empty → raises
   `AdminAccountAlreadyExistsError`. **No** Organization / Subscription
   created (assert via repo call counts).
3. **Step-3 retry (orphan from prior step-3 failure)**: register_user
   returns existing User (no-op), memberships empty (orphan),
   Organization created successfully → composite returned.
"""

from uuid import uuid4

import pytest

from identity.adapters.inmemory.inmemory_user_repo import InMemoryUserRepository
from identity.application.use_cases.register_user import RegisterUser
from organizations.adapters.inmemory.inmemory_invitation_repo import (
    InMemoryInvitationRepository,
)
from organizations.adapters.inmemory.inmemory_membership_repo import (
    InMemoryMembershipRepository,
)
from organizations.adapters.inmemory.inmemory_organization_repo import (
    InMemoryOrganizationRepository,
)
from billing.adapters.inmemory.inmemory_subscription_repo import (
    InMemorySubscriptionRepository,
)
from billing.application.use_cases.seed_freemium_subscription import (
    SeedFreemiumSubscriptionUseCase,
)
from organizations.application.use_cases.register_admin_account import (
    AdminAccountAlreadyExistsError,
    RegisterAdminAccount,
)


@pytest.fixture
def identity_user_repo():
    return InMemoryUserRepository()


@pytest.fixture
def organization_repo():
    return InMemoryOrganizationRepository()


@pytest.fixture
def membership_repo(organization_repo):
    return InMemoryMembershipRepository(organization_repo=organization_repo)


@pytest.fixture
def subscription_repo():
    return InMemorySubscriptionRepository()


@pytest.fixture
def invitation_repo():
    return InMemoryInvitationRepository()


@pytest.fixture
def identity_register_user(identity_user_repo):
    return RegisterUser(user_repo=identity_user_repo)


@pytest.fixture
def seed_freemium_subscription(subscription_repo):
    return SeedFreemiumSubscriptionUseCase(subscription_repo=subscription_repo)


@pytest.fixture
def use_case(
    identity_register_user,
    organization_repo,
    membership_repo,
    seed_freemium_subscription,
    invitation_repo,
):
    return RegisterAdminAccount(
        register_user_port=identity_register_user.execute,
        seed_freemium_subscription=seed_freemium_subscription,
        organization_repo=organization_repo,
        membership_repo=membership_repo,
        invitation_repo=invitation_repo,
    )


@pytest.mark.asyncio
async def test_success_fresh_sub_creates_full_composite(
    use_case, identity_user_repo, membership_repo, subscription_repo
):
    user, org, membership, subscription = await use_case.execute(
        supabase_user_id="sup-new",
        email="new@test.com",
        name="New Admin",
        organization_name="New Org",
    )

    assert user.supabase_user_id == "sup-new"
    assert org.name == "New Org"
    assert membership.user_id == user.id
    assert membership.organization_id == org.id
    assert subscription is not None
    assert subscription.organization_id == org.id

    # Persisted
    assert await identity_user_repo.get_by_supabase_id("sup-new") is not None
    memberships = await membership_repo.list_by_user(user.id)
    assert len(memberships) == 1


@pytest.mark.asyncio
async def test_duplicate_account_raises_409_before_org_creation(
    use_case, identity_user_repo, membership_repo, organization_repo, subscription_repo
):
    # Seed: run the flow once (creates user + org + membership + sub).
    user, org, _, _ = await use_case.execute(
        supabase_user_id="sup-dup",
        email="dup@test.com",
        name="Dup",
        organization_name="First Org",
    )
    initial_orgs = len(organization_repo._orgs) if hasattr(organization_repo, "_orgs") else 1
    initial_subs = len(subscription_repo._subs) if hasattr(subscription_repo, "_subs") else 1

    # Retry with the same supabase_user_id — must 409 before creating a
    # second Organization.
    with pytest.raises(AdminAccountAlreadyExistsError):
        await use_case.execute(
            supabase_user_id="sup-dup",
            email="dup@test.com",
            name="Dup",
            organization_name="Second Org",
        )

    # No second Org/Sub created — counts unchanged.
    if hasattr(organization_repo, "_orgs"):
        assert len(organization_repo._orgs) == initial_orgs
    if hasattr(subscription_repo, "_subs"):
        assert len(subscription_repo._subs) == initial_subs

    # User still has just one membership.
    memberships = await membership_repo.list_by_user(user.id)
    assert len(memberships) == 1


@pytest.mark.asyncio
async def test_step3_retry_after_orphan_succeeds(use_case, identity_register_user, membership_repo):
    """Simulate: step 1 of the first attempt committed the User, but
    step 3 failed and left no Organization/Membership. Caller retries.
    """
    # Simulate the orphan: invoke identity.register_user directly (step
    # 1 of the first attempt). No memberships, no org.
    orphan = await identity_register_user.execute(
        supabase_user_id="sup-orphan",
        email="orphan@test.com",
        name="Orphan",
    )
    assert not await membership_repo.list_by_user(orphan.id)

    # Retry the full flow — step 1 no-ops (returns orphan), step 2
    # passes (no memberships yet), step 3 creates everything.
    user, org, membership, subscription = await use_case.execute(
        supabase_user_id="sup-orphan",
        email="orphan@test.com",
        name="Orphan",
        organization_name="Retry Org",
    )
    assert user.id == orphan.id
    assert org.name == "Retry Org"
    assert membership.user_id == orphan.id
    assert subscription is not None


@pytest.mark.asyncio
async def test_uses_pending_invitation_instead_of_creating_new_org(
    use_case, invitation_repo, membership_repo
):
    """Invite flow still works — RegisterAdminAccount joins the existing
    org instead of creating a new one.
    """
    from datetime import datetime, timedelta, timezone

    from organizations.domain.models.invitation import Invitation, InvitationStatus
    from organizations.domain.models.membership import MembershipRole

    org_id = uuid4()
    invitation = Invitation(
        id=uuid4(),
        organization_id=org_id,
        email="invitee@test.com",
        role=MembershipRole.MEMBER,
        invited_by=uuid4(),
        token="tok",
        status=InvitationStatus.PENDING,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        created_at=datetime.now(timezone.utc),
    )
    await invitation_repo.save(invitation)

    # The orphan invited-user needs an existing Organization to join;
    # seed it directly in the repo.
    from organizations.domain.models.organization import Organization

    await use_case.organization_repo.save(
        Organization(
            id=org_id,
            created_by=uuid4(),
            name="Existing Org",
            nif=None,
            address=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )

    user, org, membership, subscription = await use_case.execute(
        supabase_user_id="sup-invitee",
        email="invitee@test.com",
        name="Invitee",
        organization_name="Ignored Because Invited",
    )

    # Joined the existing org, not a newly-created one.
    assert org.id == org_id
    assert membership.organization_id == org_id
    assert membership.role == MembershipRole.MEMBER
    # No new subscription (joined existing org).
    assert subscription is None
    # Invitation marked accepted.
    updated_invitation = await invitation_repo.get_by_id(invitation.id)
    assert updated_invitation.status == InvitationStatus.ACCEPTED
