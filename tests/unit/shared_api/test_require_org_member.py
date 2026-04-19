"""Unit test for `shared.api.dependencies.require_org_member`.

The dependency reads `request.state.memberships` directly — zero DB
round-trips (Q4 = 4.a). This test asserts both the behaviour and the
"zero DB hits" structural property by asserting the membership_repo
is never touched during the dependency evaluation.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from organizations.application.ports.repositories.membership_repository import (
    MembershipWithOrgName,
)
from organizations.domain.models.membership import MembershipRole
from shared.api.dependencies import require_org_member


def _fake_request(user, memberships):
    return SimpleNamespace(state=SimpleNamespace(user=user, memberships=memberships))


def _membership(user_id, org_id):
    now = datetime.now(timezone.utc)
    return MembershipWithOrgName(
        id=uuid4(),
        user_id=user_id,
        organization_id=org_id,
        role=MembershipRole.OWNER,
        organization_name="Acme",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_returns_user_and_membership_for_matching_org():
    user = SimpleNamespace(id=uuid4())
    org_id = uuid4()
    memberships = [_membership(user.id, org_id)]
    request = _fake_request(user, memberships)

    got_user, got_membership = await require_org_member(org_id, request)
    assert got_user is user
    assert got_membership.organization_id == org_id


@pytest.mark.asyncio
async def test_returns_403_when_no_membership_in_org():
    user = SimpleNamespace(id=uuid4())
    other_org_id = uuid4()
    request_org_id = uuid4()
    memberships = [_membership(user.id, other_org_id)]
    request = _fake_request(user, memberships)

    with pytest.raises(HTTPException) as exc:
        await require_org_member(request_org_id, request)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_returns_401_when_state_not_populated():
    # `request.state.user` and `.memberships` set to None simulates a
    # path that somehow skipped IdentityMiddleware.
    request = SimpleNamespace(state=SimpleNamespace(user=None, memberships=None))

    with pytest.raises(HTTPException) as exc:
        await require_org_member(uuid4(), request)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_zero_db_round_trips_inside_dependency():
    """The dependency must not call any repository. Mock the
    membership_repo on app.state (not that the dependency would reach it
    — the test proves it via `assert_not_called`).
    """
    mock_repo = Mock()
    mock_repo.get_by_user_and_organization = AsyncMock(return_value=None)
    mock_repo.list_by_user = AsyncMock(return_value=[])
    mock_repo.list_by_user_id_with_org_names = AsyncMock(return_value=[])

    user = SimpleNamespace(id=uuid4())
    org_id = uuid4()
    memberships = [_membership(user.id, org_id)]
    request = _fake_request(user, memberships)
    # Attach the mock repo as if via app.state — the dependency should
    # not reach for it.
    request.app = SimpleNamespace(state=SimpleNamespace(membership_repo=mock_repo))

    await require_org_member(org_id, request)

    mock_repo.get_by_user_and_organization.assert_not_called()
    mock_repo.list_by_user.assert_not_called()
    mock_repo.list_by_user_id_with_org_names.assert_not_called()
