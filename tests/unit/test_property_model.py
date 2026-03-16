from datetime import date, datetime, timezone
from uuid import uuid4

from property_management.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)
from property_management.domain.models.property_owner import (
    CivilStatus,
    DocumentType,
    PropertyOwner,
)


class TestPropertyModel:
    def test_create_property(self):
        now = datetime.now(timezone.utc)
        prop = Property(
            id=uuid4(),
            user_id=uuid4(),
            address="Rua das Flores 123, Porto",
            listing_type=ListingType.SALE,
            typology=Typology.APARTMENT,
            status=PropertyStatus.DRAFT,
            description="Beautiful apartment",
            created_at=now,
            updated_at=now,
        )
        assert prop.listing_type == ListingType.SALE
        assert prop.typology == Typology.APARTMENT
        assert prop.status == PropertyStatus.DRAFT
        assert prop.description == "Beautiful apartment"
        assert prop.owners == []

    def test_create_property_without_description(self):
        now = datetime.now(timezone.utc)
        prop = Property(
            id=uuid4(),
            user_id=uuid4(),
            address="Rua das Flores 123, Porto",
            listing_type=ListingType.PURCHASE,
            typology=Typology.HOUSE,
            status=PropertyStatus.ACTIVE,
            description=None,
            created_at=now,
            updated_at=now,
        )
        assert prop.description is None

    def test_add_owner(self):
        now = datetime.now(timezone.utc)
        prop_id = uuid4()
        prop = Property(
            id=prop_id,
            user_id=uuid4(),
            address="Rua das Flores 123, Porto",
            listing_type=ListingType.SALE,
            typology=Typology.APARTMENT,
            status=PropertyStatus.DRAFT,
            description=None,
            created_at=now,
            updated_at=now,
        )
        owner = PropertyOwner(
            id=uuid4(),
            property_id=prop_id,
            full_name="Maria Silva",
            civil_status=CivilStatus.SINGLE,
            address="Rua do Exemplo 1",
            nif="123456789",
            document_type=DocumentType.CARTAO_CIDADAO,
            document_id="12345678",
            issued_by="SEF",
            issuing_district=None,
            date_of_birth=date(1990, 1, 1),
            created_at=now,
            updated_at=now,
        )
        prop.add_owner(owner)
        assert len(prop.owners) == 1
        assert prop.owners[0].full_name == "Maria Silva"

    def test_get_owner(self):
        now = datetime.now(timezone.utc)
        prop_id = uuid4()
        owner_id = uuid4()
        prop = Property(
            id=prop_id,
            user_id=uuid4(),
            address="Rua das Flores 123, Porto",
            listing_type=ListingType.SALE,
            typology=Typology.APARTMENT,
            status=PropertyStatus.DRAFT,
            description=None,
            created_at=now,
            updated_at=now,
        )
        owner = PropertyOwner(
            id=owner_id,
            property_id=prop_id,
            full_name="Maria Silva",
            civil_status=CivilStatus.SINGLE,
            address="Rua do Exemplo 1",
            nif="123456789",
            document_type=DocumentType.CARTAO_CIDADAO,
            document_id="12345678",
            issued_by="SEF",
            issuing_district=None,
            date_of_birth=date(1990, 1, 1),
            created_at=now,
            updated_at=now,
        )
        prop.add_owner(owner)
        assert prop.get_owner(owner_id) == owner
        assert prop.get_owner(uuid4()) is None

    def test_listing_type_values(self):
        assert ListingType.SALE.value == "sale"
        assert ListingType.PURCHASE.value == "purchase"

    def test_typology_values(self):
        assert Typology.APARTMENT.value == "apartment"
        assert Typology.HOUSE.value == "house"
        assert Typology.LAND.value == "land"
        assert Typology.RUIN.value == "ruin"

    def test_property_status_values(self):
        assert PropertyStatus.DRAFT.value == "draft"
        assert PropertyStatus.ACTIVE.value == "active"
        assert PropertyStatus.SOLD.value == "sold"
        assert PropertyStatus.RENTED.value == "rented"
        assert PropertyStatus.WITHDRAWN.value == "withdrawn"
