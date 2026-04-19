"""Unit tests for `IdentityMiddleware`.

Cases (per spec `§Test changes` → "unit tests"):
- public path → bypass
- REGISTRATION_PATHS → bypass User/membership checks
- `/admin/*` + no User → 401
- `/admin/*` + User + no memberships → 403
- `/admin/*` + User + memberships → pass, state populated
- `/portal/*` + User + no memberships → pass
- `/portal/*` + User + memberships → pass (admins can hit portal)
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import Response

from identity.domain.models.user import User
from organizations.application.ports.repositories.membership_repository import (
    MembershipWithOrgName,
)
from organizations.domain.models.membership import MembershipRole
from shared.api.middleware import IdentityMiddleware


def _user():
    now = datetime.now(timezone.utc)
    return User(
        id=uuid4(),
        supabase_user_id="sup-test",
        email="u@test.com",
        name="U",
        phone=None,
        google_metadata=None,
        created_at=now,
        updated_at=now,
    )


def _membership(user):
    now = datetime.now(timezone.utc)
    return MembershipWithOrgName(
        id=uuid4(),
        user_id=user.id,
        organization_id=uuid4(),
        role=MembershipRole.OWNER,
        organization_name="Acme",
        created_at=now,
        updated_at=now,
    )


def _fake_request(path, *, sub="sup-test", method="GET", identity_container=None, orgs_container=None):
    state = SimpleNamespace(supabase_user_id=sub)
    app_state = SimpleNamespace(
        identity_container=identity_container,
        organizations_container=orgs_container,
    )
    return SimpleNamespace(
        url=SimpleNamespace(path=path),
        method=method,
        state=state,
        app=SimpleNamespace(state=app_state),
    )


async def _pass_through(request):
    return Response(content="ok", status_code=200)


@pytest.fixture
def middleware():
    return IdentityMiddleware(app=None)


# ── public paths + OPTIONS ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_public_path_bypasses(middleware):
    request = _fake_request("/api/v1/health")
    resp = await middleware.dispatch(request, _pass_through)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_options_bypasses(middleware):
    request = _fake_request("/api/v1/admin/properties", method="OPTIONS")
    resp = await middleware.dispatch(request, _pass_through)
    assert resp.status_code == 200


# ── registration paths bypass identity lookups ──────────────────────────────


@pytest.mark.asyncio
async def test_admin_registration_path_bypasses_user_lookup(middleware):
    request = _fake_request("/api/v1/admin/auth/register")
    resp = await middleware.dispatch(request, _pass_through)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_portal_registration_path_bypasses_user_lookup(middleware):
    request = _fake_request("/api/v1/portal/auth/register")
    resp = await middleware.dispatch(request, _pass_through)
    assert resp.status_code == 200


# ── 401 when no supabase_user_id ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_sub_returns_401(middleware):
    request = _fake_request("/api/v1/admin/properties", sub=None)
    resp = await middleware.dispatch(request, _pass_through)
    assert resp.status_code == 401


# ── 401 when user not found ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_path_with_unknown_user_returns_401(middleware):
    find_user = SimpleNamespace(by_supabase_id=AsyncMock(return_value=None))
    identity = SimpleNamespace(find_user=find_user)
    orgs = SimpleNamespace(membership_repo=None)

    request = _fake_request(
        "/api/v1/admin/properties",
        identity_container=identity,
        orgs_container=orgs,
    )
    resp = await middleware.dispatch(request, _pass_through)
    assert resp.status_code == 401


# ── 403 admin path + no memberships ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_path_with_user_but_no_memberships_returns_403(middleware):
    user = _user()
    find_user = SimpleNamespace(by_supabase_id=AsyncMock(return_value=user))
    membership_repo = SimpleNamespace(list_by_user_id_with_org_names=AsyncMock(return_value=[]))

    identity = SimpleNamespace(find_user=find_user)
    orgs = SimpleNamespace(membership_repo=membership_repo)

    request = _fake_request(
        "/api/v1/admin/properties",
        identity_container=identity,
        orgs_container=orgs,
    )
    resp = await middleware.dispatch(request, _pass_through)
    assert resp.status_code == 403


# ── admin path + memberships → pass ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_path_with_memberships_passes_and_populates_state(middleware):
    user = _user()
    membership = _membership(user)
    find_user = SimpleNamespace(by_supabase_id=AsyncMock(return_value=user))
    membership_repo = SimpleNamespace(
        list_by_user_id_with_org_names=AsyncMock(return_value=[membership])
    )

    identity = SimpleNamespace(find_user=find_user)
    orgs = SimpleNamespace(membership_repo=membership_repo)

    request = _fake_request(
        "/api/v1/admin/properties",
        identity_container=identity,
        orgs_container=orgs,
    )
    resp = await middleware.dispatch(request, _pass_through)
    assert resp.status_code == 200
    assert request.state.user is user
    assert request.state.memberships == [membership]


# ── portal paths: no memberships → pass; memberships → pass ─────────────────


@pytest.mark.asyncio
async def test_portal_path_with_no_memberships_passes(middleware):
    user = _user()
    find_user = SimpleNamespace(by_supabase_id=AsyncMock(return_value=user))
    membership_repo = SimpleNamespace(list_by_user_id_with_org_names=AsyncMock(return_value=[]))

    identity = SimpleNamespace(find_user=find_user)
    orgs = SimpleNamespace(membership_repo=membership_repo)

    request = _fake_request(
        "/api/v1/portal/bookings/123",
        identity_container=identity,
        orgs_container=orgs,
    )
    resp = await middleware.dispatch(request, _pass_through)
    assert resp.status_code == 200
    assert request.state.memberships == []


@pytest.mark.asyncio
async def test_portal_path_with_memberships_passes(middleware):
    user = _user()
    membership = _membership(user)
    find_user = SimpleNamespace(by_supabase_id=AsyncMock(return_value=user))
    membership_repo = SimpleNamespace(
        list_by_user_id_with_org_names=AsyncMock(return_value=[membership])
    )

    identity = SimpleNamespace(find_user=find_user)
    orgs = SimpleNamespace(membership_repo=membership_repo)

    request = _fake_request(
        "/api/v1/portal/bookings/123",
        identity_container=identity,
        orgs_container=orgs,
    )
    resp = await middleware.dispatch(request, _pass_through)
    assert resp.status_code == 200
