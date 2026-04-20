from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from organizations.domain.models.membership import Membership, MembershipRole
from organizations.domain.models.organization import Organization
from organizations.domain.models.user import User
from organizations.domain.models.value_objects import PhoneNumber


def _make_organization(**overrides) -> Organization:
    now = datetime.now(timezone.utc)
    defaults = {
        "id": uuid4(),
        "created_by": uuid4(),
        "name": "Test Organization",
        "nif": "123456789",
        "address": "Rua do Teste 1, Lisboa",
        "created_at": now,
        "updated_at": now,
    }
    return Organization(**(defaults | overrides))


def _make_user(organization_id=None, **overrides) -> User:
    now = datetime.now(timezone.utc)
    defaults = {
        "id": uuid4(),
        "supabase_user_id": str(uuid4()),
        "email": f"user-{uuid4().hex[:8]}@test.com",
        "name": "Test User",
        "phone": PhoneNumber(country_code="+351", number="912345678"),
        "google_metadata": None,
        "created_at": now,
        "updated_at": now,
    }
    return User(**(defaults | overrides))


def _make_membership(user_id, organization_id, **overrides) -> Membership:
    now = datetime.now(timezone.utc)
    defaults = {
        "id": uuid4(),
        "user_id": user_id,
        "organization_id": organization_id,
        "role": MembershipRole.MEMBER,
        "created_at": now,
        "updated_at": now,
    }
    return Membership(**(defaults | overrides))


async def test_save_and_get_membership(organization_repo, user_repo, membership_repo):
    org = await organization_repo.save(_make_organization())
    user = await user_repo.save(_make_user(org.id))
    membership = _make_membership(user.id, org.id, role=MembershipRole.OWNER)

    saved = await membership_repo.save(membership)
    assert saved.id == membership.id
    assert saved.role == MembershipRole.OWNER

    fetched = await membership_repo.get_by_id(membership.id)
    assert fetched is not None
    assert fetched.user_id == user.id
    assert fetched.organization_id == org.id
    assert fetched.role == MembershipRole.OWNER


async def test_get_by_user_and_organization(organization_repo, user_repo, membership_repo):
    org = await organization_repo.save(_make_organization())
    user = await user_repo.save(_make_user(org.id))
    membership = _make_membership(user.id, org.id)
    await membership_repo.save(membership)

    fetched = await membership_repo.get_by_user_and_organization(user.id, org.id)
    assert fetched is not None
    assert fetched.id == membership.id


async def test_list_by_organization(organization_repo, user_repo, membership_repo):
    org = await organization_repo.save(_make_organization())
    user1 = await user_repo.save(_make_user(org.id))
    user2 = await user_repo.save(_make_user(org.id))

    await membership_repo.save(_make_membership(user1.id, org.id, role=MembershipRole.OWNER))
    await membership_repo.save(_make_membership(user2.id, org.id, role=MembershipRole.MEMBER))

    members = await membership_repo.list_by_organization(org.id)
    assert len(members) == 2


async def test_list_by_user(organization_repo, user_repo, membership_repo):
    org1 = await organization_repo.save(_make_organization())
    org2 = await organization_repo.save(_make_organization())
    user = await user_repo.save(_make_user(org1.id))

    await membership_repo.save(_make_membership(user.id, org1.id))
    await membership_repo.save(_make_membership(user.id, org2.id))

    memberships = await membership_repo.list_by_user(user.id)
    assert len(memberships) == 2


async def test_update_membership_role(organization_repo, user_repo, membership_repo):
    org = await organization_repo.save(_make_organization())
    user = await user_repo.save(_make_user(org.id))
    membership = _make_membership(user.id, org.id, role=MembershipRole.MEMBER)
    await membership_repo.save(membership)

    membership.role = MembershipRole.ADMIN
    updated = await membership_repo.update(membership)
    assert updated.role == MembershipRole.ADMIN

    fetched = await membership_repo.get_by_id(membership.id)
    assert fetched.role == MembershipRole.ADMIN


async def test_delete_membership(organization_repo, user_repo, membership_repo):
    org = await organization_repo.save(_make_organization())
    user = await user_repo.save(_make_user(org.id))
    membership = _make_membership(user.id, org.id)
    await membership_repo.save(membership)

    await membership_repo.delete(membership.id)

    fetched = await membership_repo.get_by_id(membership.id)
    assert fetched is None


async def test_unique_constraint_user_organization(organization_repo, user_repo, membership_repo):
    org = await organization_repo.save(_make_organization())
    user = await user_repo.save(_make_user(org.id))

    await membership_repo.save(_make_membership(user.id, org.id))

    with pytest.raises(IntegrityError):
        await membership_repo.save(_make_membership(user.id, org.id))
