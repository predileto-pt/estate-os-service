from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from core_api.domain.models.company import Company
from core_api.domain.models.user import User
from core_api.domain.models.value_objects import PhoneNumber


def _make_company(**overrides) -> Company:
    now = datetime.now(timezone.utc)
    defaults = {
        "id": uuid4(),
        "user_id": uuid4(),
        "name": "Test Company",
        "nif": "123456789",
        "address": "Rua do Teste 1, Lisboa",
        "created_at": now,
        "updated_at": now,
    }
    return Company(**(defaults | overrides))


def _make_user(company_id, **overrides) -> User:
    now = datetime.now(timezone.utc)
    defaults = {
        "id": uuid4(),
        "supabase_user_id": str(uuid4()),
        "email": f"user-{uuid4().hex[:8]}@test.com",
        "name": "Test User",
        "phone": PhoneNumber(country_code="+351", number="912345678"),
        "company_id": company_id,
        "google_metadata": None,
        "created_at": now,
        "updated_at": now,
    }
    return User(**(defaults | overrides))


async def test_save_and_get_user(company_repo, user_repo):
    company = await company_repo.save(_make_company())
    user = _make_user(company.id)

    saved = await user_repo.save(user)
    assert saved.id == user.id
    assert saved.email == user.email

    fetched = await user_repo.get_by_id(user.id)
    assert fetched is not None
    assert fetched.name == user.name
    assert fetched.phone == user.phone


async def test_get_by_supabase_id(company_repo, user_repo):
    company = await company_repo.save(_make_company())
    user = _make_user(company.id)
    await user_repo.save(user)

    fetched = await user_repo.get_by_supabase_id(user.supabase_user_id)
    assert fetched is not None
    assert fetched.id == user.id


async def test_get_by_email(company_repo, user_repo):
    company = await company_repo.save(_make_company())
    user = _make_user(company.id)
    await user_repo.save(user)

    fetched = await user_repo.get_by_email(user.email)
    assert fetched is not None
    assert fetched.id == user.id


async def test_update_user(company_repo, user_repo):
    company = await company_repo.save(_make_company())
    user = _make_user(company.id)
    await user_repo.save(user)

    user.name = "Updated Name"
    user.phone = PhoneNumber(country_code="+34", number="611222333")
    updated = await user_repo.update(user)

    assert updated.name == "Updated Name"
    assert updated.phone.country_code == "+34"
    assert updated.phone.number == "611222333"


async def test_user_email_unique_constraint(company_repo, user_repo):
    company = await company_repo.save(_make_company())
    email = "duplicate@test.com"
    await user_repo.save(_make_user(company.id, email=email))

    with pytest.raises(IntegrityError):
        await user_repo.save(_make_user(company.id, email=email))


async def test_user_requires_company(user_repo):
    user = _make_user(company_id=uuid4())  # non-existent company
    with pytest.raises(IntegrityError):
        await user_repo.save(user)
