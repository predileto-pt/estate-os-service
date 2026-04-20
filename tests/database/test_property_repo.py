from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from organizations.domain.models.organization import Organization
from organizations.domain.models.user import User
from organizations.domain.models.value_objects import PhoneNumber
from properties.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)
from properties.domain.models.property_owner import PropertyOwner
from properties.domain.models.property_price import PropertyPrice


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


def _make_property(organization_id, **overrides) -> Property:
    now = datetime.now(timezone.utc)
    defaults = {
        "id": uuid4(),
        "organization_id": organization_id,
        "address": "Rua da Propriedade 1, Lisboa",
        "listing_type": ListingType.SALE,
        "typology": Typology.APARTMENT,
        "status": PropertyStatus.DRAFT,
        "description": "A test property",
        "created_at": now,
        "updated_at": now,
        "characteristics": None,
        "owners": [],
    }
    return Property(**(defaults | overrides))


def _make_owner(property_id, **overrides) -> PropertyOwner:
    now = datetime.now(timezone.utc)
    defaults = {
        "id": uuid4(),
        "property_id": property_id,
        "full_name": "João Silva",
        "civil_status": None,
        "address": "Rua do Proprietário 1, Porto",
        "nif": "123456789",
        "document_type": None,
        "document_id": None,
        "issued_by": None,
        "issuing_district": None,
        "date_of_birth": None,
        "created_at": now,
        "updated_at": now,
    }
    return PropertyOwner(**(defaults | overrides))


async def test_save_and_get_property(organization_repo, user_repo, property_repo):
    org = await organization_repo.save(_make_organization())
    await user_repo.save(_make_user(org.id))
    prop = _make_property(org.id)

    saved = await property_repo.save(prop)
    assert saved.id == prop.id
    assert saved.listing_type == ListingType.SALE
    assert saved.typology == Typology.APARTMENT

    fetched = await property_repo.get_by_id(prop.id)
    assert fetched is not None
    assert fetched.address == prop.address
    assert fetched.status == PropertyStatus.DRAFT


async def test_list_by_organization(organization_repo, user_repo, property_repo):
    org = await organization_repo.save(_make_organization())
    await user_repo.save(_make_user(org.id))

    for i in range(3):
        await property_repo.save(_make_property(org.id, address=f"Rua {i}"))

    properties = await property_repo.list_by_organization(org.id)
    assert len(properties) == 3


async def test_save_owner_and_get_with_property(organization_repo, user_repo, property_repo):
    org = await organization_repo.save(_make_organization())
    await user_repo.save(_make_user(org.id))
    prop = _make_property(org.id)
    saved_prop = await property_repo.save(prop)

    owner = _make_owner(saved_prop.id)
    updated_prop = await property_repo.save_owner(saved_prop, owner)

    assert len(updated_prop.owners) == 1
    assert updated_prop.owners[0].full_name == "João Silva"
    assert updated_prop.owners[0].nif == "123456789"

    # Verify owners persist when fetched again
    fetched = await property_repo.get_by_id(prop.id)
    assert len(fetched.owners) == 1


def _make_price(property_id, **overrides) -> PropertyPrice:
    now = datetime.now(timezone.utc)
    defaults = {
        "id": uuid4(),
        "property_id": property_id,
        "amount": Decimal("250000.00"),
        "listing_type": ListingType.SALE,
        "created_at": now,
        "updated_at": now,
    }
    return PropertyPrice(**(defaults | overrides))


async def test_save_price_and_get_with_property(organization_repo, user_repo, property_repo):
    org = await organization_repo.save(_make_organization())
    await user_repo.save(_make_user(org.id))
    prop = _make_property(org.id)
    saved_prop = await property_repo.save(prop)

    price = _make_price(saved_prop.id)
    updated_prop = await property_repo.save_price(saved_prop, price)

    assert len(updated_prop.prices) == 1
    assert updated_prop.prices[0].amount == Decimal("250000.00")
    assert updated_prop.prices[0].listing_type == ListingType.SALE

    # Verify prices persist when fetched again
    fetched = await property_repo.get_by_id(prop.id)
    assert len(fetched.prices) == 1


async def test_get_nonexistent_property(property_repo):
    result = await property_repo.get_by_id(uuid4())
    assert result is None
