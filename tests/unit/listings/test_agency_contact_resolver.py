"""Unit tests for `AgencyContactResolver` (organizations side adapter)."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from identity.adapters.inmemory.inmemory_user_repo import (
    InMemoryUserRepository as InMemoryIdentityUserRepository,
)
from identity.domain.models.user import User as IdentityUser
from identity.domain.value_objects import PhoneNumber
from listings.application.ports.get_agency_contact import AgencyContact
from organizations.adapters.composition.agency_contact_resolver import (
    AgencyContactResolver,
)
from organizations.adapters.inmemory.inmemory_organization_repo import (
    InMemoryOrganizationRepository,
)
from organizations.domain.models.organization import Organization


def _make_user(*, user_id: UUID, phone: PhoneNumber | None = None) -> IdentityUser:
    now = datetime.now(timezone.utc)
    return IdentityUser(
        id=user_id,
        supabase_user_id=f"sub-{user_id}",
        email="agency@example.com",
        name="Agency Owner",
        phone=phone,
        google_metadata=None,
        created_at=now,
        updated_at=now,
    )


def _make_org(
    *, org_id: UUID, created_by: UUID, name: str | None = "Predileto Imobiliária"
) -> Organization:
    now = datetime.now(timezone.utc)
    return Organization(
        id=org_id,
        created_by=created_by,
        name=name,
        nif=None,
        address=None,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def org_repo():
    return InMemoryOrganizationRepository()


@pytest.fixture
def user_repo():
    return InMemoryIdentityUserRepository()


@pytest.fixture
def resolver(org_repo, user_repo):
    return AgencyContactResolver(organization_repo=org_repo, user_repo=user_repo)


async def test_resolves_name_email_and_phone_when_user_has_phone(resolver, org_repo, user_repo):
    user_id = uuid4()
    org_id = uuid4()
    await user_repo.save(
        _make_user(user_id=user_id, phone=PhoneNumber(country_code="+351", number="912345678"))
    )
    await org_repo.save(_make_org(org_id=org_id, created_by=user_id))

    contact = await resolver.execute(org_id)

    assert contact == AgencyContact(
        name="Predileto Imobiliária",
        email="agency@example.com",
        phone="+351 912345678",
    )


async def test_phone_is_none_when_user_has_no_phone(resolver, org_repo, user_repo):
    user_id = uuid4()
    org_id = uuid4()
    await user_repo.save(_make_user(user_id=user_id, phone=None))
    await org_repo.save(_make_org(org_id=org_id, created_by=user_id))

    contact = await resolver.execute(org_id)

    assert contact.name == "Predileto Imobiliária"
    assert contact.email == "agency@example.com"
    assert contact.phone is None


async def test_returns_all_nones_when_org_missing(resolver):
    contact = await resolver.execute(uuid4())
    assert contact == AgencyContact(name=None, email=None, phone=None)


async def test_email_phone_none_when_creating_user_missing(resolver, org_repo):
    org_id = uuid4()
    await org_repo.save(_make_org(org_id=org_id, created_by=uuid4()))  # user not saved

    contact = await resolver.execute(org_id)

    assert contact.name == "Predileto Imobiliária"
    assert contact.email is None
    assert contact.phone is None
