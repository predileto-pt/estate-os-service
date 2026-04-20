from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from organizations.domain.models.membership import Membership, MembershipRole
from shared.api.dependencies import (
    require_current_org,
    require_current_org_admin,
    require_org_admin,
    require_org_member,
)


def _user():
    now = datetime.now(timezone.utc)
    return SimpleNamespace(id=uuid4(), email="x@y.com", name="X", created_at=now)


def _membership(org_id, role: MembershipRole):
    now = datetime.now(timezone.utc)
    return Membership(
        id=uuid4(),
        user_id=uuid4(),
        organization_id=org_id,
        role=role,
        created_at=now,
        updated_at=now,
    )


def _request(user, memberships):
    return SimpleNamespace(state=SimpleNamespace(user=user, memberships=memberships))


# ── require_org_admin (path-param variant) ──────────────────────────────────


async def test_require_org_admin_owner_allowed():
    org_id = uuid4()
    m = _membership(org_id, MembershipRole.OWNER)
    user, membership = await require_org_admin(org_id, _request(_user(), [m]))
    assert membership.role == MembershipRole.OWNER


async def test_require_org_admin_admin_allowed():
    org_id = uuid4()
    m = _membership(org_id, MembershipRole.ADMIN)
    _, membership = await require_org_admin(org_id, _request(_user(), [m]))
    assert membership.role == MembershipRole.ADMIN


async def test_require_org_admin_member_rejected():
    org_id = uuid4()
    m = _membership(org_id, MembershipRole.MEMBER)
    with pytest.raises(HTTPException) as exc:
        await require_org_admin(org_id, _request(_user(), [m]))
    assert exc.value.status_code == 403


async def test_require_org_admin_no_membership_rejected():
    org_id = uuid4()
    other_org = uuid4()
    m = _membership(other_org, MembershipRole.OWNER)
    with pytest.raises(HTTPException) as exc:
        await require_org_admin(org_id, _request(_user(), [m]))
    assert exc.value.status_code == 403


async def test_require_org_admin_unauthed_rejected():
    with pytest.raises(HTTPException) as exc:
        await require_org_admin(uuid4(), _request(None, None))
    assert exc.value.status_code == 401


# ── require_org_member still works for MEMBER ───────────────────────────────


async def test_require_org_member_accepts_member():
    org_id = uuid4()
    m = _membership(org_id, MembershipRole.MEMBER)
    _, membership = await require_org_member(org_id, _request(_user(), [m]))
    assert membership.role == MembershipRole.MEMBER


# ── require_current_org(_admin) — no org_id param variant ───────────────────


async def test_require_current_org_single_membership():
    org_id = uuid4()
    m = _membership(org_id, MembershipRole.MEMBER)
    _, membership = await require_current_org(_request(_user(), [m]))
    assert membership.organization_id == org_id


async def test_require_current_org_no_memberships():
    with pytest.raises(HTTPException) as exc:
        await require_current_org(_request(_user(), []))
    assert exc.value.status_code == 403


async def test_require_current_org_ambiguous_memberships():
    m1 = _membership(uuid4(), MembershipRole.OWNER)
    m2 = _membership(uuid4(), MembershipRole.OWNER)
    with pytest.raises(HTTPException) as exc:
        await require_current_org(_request(_user(), [m1, m2]))
    assert exc.value.status_code == 400


async def test_require_current_org_admin_member_rejected():
    m = _membership(uuid4(), MembershipRole.MEMBER)
    with pytest.raises(HTTPException) as exc:
        await require_current_org_admin(_request(_user(), [m]))
    assert exc.value.status_code == 403
