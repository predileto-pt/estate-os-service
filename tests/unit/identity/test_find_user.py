"""Unit tests for `identity.application.use_cases.find_user.FindUser`.

Two methods, two use sites:
- `by_id(id)` — bound as `UserLookupById` callable Protocol, used by
  organizations (cross-context).
- `by_supabase_id(supabase_user_id)` — used directly by
  `IdentityMiddleware` (shared infrastructure, no Protocol per Q2 = 2.b).
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from identity.adapters.inmemory.inmemory_user_repo import InMemoryUserRepository
from identity.application.ports.user_lookup import UserLookupById
from identity.application.use_cases.find_user import FindUser
from identity.domain.models.user import User


@pytest.fixture
def user_repo():
    return InMemoryUserRepository()


@pytest.fixture
def use_case(user_repo):
    return FindUser(user_repo=user_repo)


@pytest.fixture
async def seeded_user(user_repo):
    now = datetime.now(timezone.utc)
    u = User(
        id=uuid4(),
        supabase_user_id="sup-known",
        email="u@test.com",
        name="U",
        phone=None,
        google_metadata=None,
        created_at=now,
        updated_at=now,
    )
    await user_repo.save(u)
    return u


@pytest.mark.asyncio
async def test_by_id_returns_user_for_known_id(use_case, seeded_user):
    found = await use_case.by_id(seeded_user.id)
    assert found is not None
    assert found.id == seeded_user.id


@pytest.mark.asyncio
async def test_by_id_returns_none_for_unknown_id(use_case):
    result = await use_case.by_id(uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_by_supabase_id_returns_user_for_known_sub(use_case, seeded_user):
    found = await use_case.by_supabase_id("sup-known")
    assert found is not None
    assert found.id == seeded_user.id


@pytest.mark.asyncio
async def test_by_supabase_id_returns_none_for_unknown_sub(use_case):
    result = await use_case.by_supabase_id("sup-unknown")
    assert result is None


def test_by_id_satisfies_user_lookup_by_id_port():
    """`FindUser.by_id` is bindable to `UserLookupById` callable Protocol."""
    uc = FindUser(user_repo=InMemoryUserRepository())
    port: UserLookupById = uc.by_id
    assert callable(port)
    assert port.__self__ is uc
