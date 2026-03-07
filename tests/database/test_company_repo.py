from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from core_api.domain.models.company import Company


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


async def test_save_and_get_company(company_repo):
    company = _make_company()
    saved = await company_repo.save(company)

    assert saved.id == company.id
    assert saved.name == company.name
    assert saved.nif == company.nif

    fetched = await company_repo.get_by_id(company.id)
    assert fetched is not None
    assert fetched.id == company.id
    assert fetched.name == company.name
    assert fetched.nif == company.nif
    assert fetched.address == company.address


async def test_update_company(company_repo):
    company = _make_company()
    await company_repo.save(company)

    company.name = "Updated Company"
    company.nif = "987654321"
    company.address = "Rua Nova 2, Porto"
    updated = await company_repo.update(company)

    assert updated.name == "Updated Company"
    assert updated.nif == "987654321"
    assert updated.address == "Rua Nova 2, Porto"

    fetched = await company_repo.get_by_id(company.id)
    assert fetched.name == "Updated Company"


async def test_get_nonexistent_company(company_repo):
    result = await company_repo.get_by_id(uuid4())
    assert result is None


async def test_company_user_id_unique_constraint(company_repo):
    shared_user_id = uuid4()
    await company_repo.save(_make_company(user_id=shared_user_id))

    with pytest.raises(IntegrityError):
        await company_repo.save(_make_company(user_id=shared_user_id))
