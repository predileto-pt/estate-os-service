"""Unit tests for `identity.application.use_cases.register_user.RegisterUser`.

Covers:
- Success: new `supabase_user_id` creates a User row.
- **Idempotency**: duplicate `supabase_user_id` returns the existing
  User without raising (Q3 = 3.a).
- `RegisterUser.execute` is bindable to the `RegisterUserPort` callable
  Protocol (structural conformance check).
"""

import pytest

from identity.adapters.inmemory.inmemory_user_repo import InMemoryUserRepository
from identity.application.ports.register_user_port import RegisterUserPort
from identity.application.use_cases.register_user import RegisterUser
from identity.domain.value_objects import PhoneNumber


@pytest.fixture
def user_repo():
    return InMemoryUserRepository()


@pytest.fixture
def use_case(user_repo):
    return RegisterUser(user_repo=user_repo)


@pytest.mark.asyncio
async def test_register_user_creates_row(use_case, user_repo):
    user = await use_case.execute(
        supabase_user_id="sup-abc",
        email="alice@test.com",
        name="Alice",
    )
    assert user.supabase_user_id == "sup-abc"
    assert user.email == "alice@test.com"
    assert user.name == "Alice"
    # Persisted
    found = await user_repo.get_by_supabase_id("sup-abc")
    assert found is not None
    assert found.id == user.id


@pytest.mark.asyncio
async def test_register_user_with_phone(use_case):
    phone = PhoneNumber(country_code="+351", number="912345678")
    user = await use_case.execute(
        supabase_user_id="sup-phone",
        email="bob@test.com",
        name="Bob",
        phone=phone,
    )
    assert user.phone == phone


@pytest.mark.asyncio
async def test_register_user_is_idempotent_on_duplicate_sub(use_case, user_repo):
    """Duplicate supabase_user_id returns the existing User — not a 409."""
    first = await use_case.execute(
        supabase_user_id="sup-dup",
        email="carol@test.com",
        name="Carol",
    )
    second = await use_case.execute(
        supabase_user_id="sup-dup",
        email="anything@test.com",  # intentionally different email
        name="IgnoredName",
    )
    assert first.id == second.id
    assert second.email == "carol@test.com"  # original row returned
    assert second.name == "Carol"

    # Only one row in the repo
    all_users = [u async for u in _iter_repo(user_repo)]
    assert len(all_users) == 1


async def _iter_repo(repo: InMemoryUserRepository):
    for u in repo._users.values():
        yield u


def test_register_user_satisfies_register_user_port():
    """`RegisterUser.execute` is bindable to the `RegisterUserPort`
    callable Protocol (Q1 = 1.c). Structural check — Protocol with
    `__call__` is duck-typed by any async callable of the right shape.
    """
    uc = RegisterUser(user_repo=InMemoryUserRepository())
    port: RegisterUserPort = uc.execute  # type-check assignment
    assert callable(port)
    # Bound method re-binds on every access, so `is` won't equal; the
    # structural test is that the assignment above type-checks AND the
    # method reference points at the use case instance.
    assert port.__self__ is uc
