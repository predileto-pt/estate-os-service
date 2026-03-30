from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from customers.domain.models.organization import Organization


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


async def test_save_and_get_organization(organization_repo):
    org = _make_organization()
    saved = await organization_repo.save(org)

    assert saved.id == org.id
    assert saved.name == org.name
    assert saved.nif == org.nif

    fetched = await organization_repo.get_by_id(org.id)
    assert fetched is not None
    assert fetched.id == org.id
    assert fetched.name == org.name
    assert fetched.nif == org.nif
    assert fetched.address == org.address


async def test_update_organization(organization_repo):
    org = _make_organization()
    await organization_repo.save(org)

    org.name = "Updated Organization"
    org.nif = "987654321"
    org.address = "Rua Nova 2, Porto"
    updated = await organization_repo.update(org)

    assert updated.name == "Updated Organization"
    assert updated.nif == "987654321"
    assert updated.address == "Rua Nova 2, Porto"

    fetched = await organization_repo.get_by_id(org.id)
    assert fetched.name == "Updated Organization"


async def test_get_nonexistent_organization(organization_repo):
    result = await organization_repo.get_by_id(uuid4())
    assert result is None


async def test_organization_created_by_unique_constraint(organization_repo):
    shared_created_by = uuid4()
    await organization_repo.save(_make_organization(created_by=shared_created_by))

    with pytest.raises(IntegrityError):
        await organization_repo.save(_make_organization(created_by=shared_created_by))
