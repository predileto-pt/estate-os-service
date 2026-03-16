from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

from property_management.domain.exceptions import InvalidNIFError
from property_management.domain.models.property_owner import (
    CivilStatus,
    DocumentType,
    PropertyOwner,
)


class TestPropertyOwnerModel:
    def test_create_property_owner(self):
        now = datetime.now(timezone.utc)
        owner = PropertyOwner(
            id=uuid4(),
            property_id=uuid4(),
            full_name="Maria Silva Santos",
            civil_status=CivilStatus.MARRIED,
            address="Rua das Flores 123, 4000-001 Porto",
            nif="123456789",
            document_type=DocumentType.CARTAO_CIDADAO,
            document_id="12345678",
            issued_by="Servicos de Identificacao Civil de Porto",
            issuing_district="Porto",
            date_of_birth=date(1985, 6, 15),
            created_at=now,
            updated_at=now,
        )
        assert owner.full_name == "Maria Silva Santos"
        assert owner.civil_status == CivilStatus.MARRIED
        assert owner.nif == "123456789"
        assert owner.document_type == DocumentType.CARTAO_CIDADAO

    def test_create_property_owner_without_issuing_district(self):
        now = datetime.now(timezone.utc)
        owner = PropertyOwner(
            id=uuid4(),
            property_id=uuid4(),
            full_name="Joao Silva",
            civil_status=CivilStatus.SINGLE,
            address="Rua do Exemplo 1, Lisboa",
            nif="987654321",
            document_type=DocumentType.PASSPORT,
            document_id="AB123456",
            issued_by="SEF",
            issuing_district=None,
            date_of_birth=date(1990, 1, 1),
            created_at=now,
            updated_at=now,
        )
        assert owner.issuing_district is None

    def test_invalid_nif_not_digits(self):
        with pytest.raises(InvalidNIFError):
            PropertyOwner(
                id=uuid4(),
                property_id=uuid4(),
                full_name="Test",
                civil_status=CivilStatus.SINGLE,
                address="Test",
                nif="12345678A",
                document_type=DocumentType.CARTAO_CIDADAO,
                document_id="12345678",
                issued_by="Test",
                issuing_district=None,
                date_of_birth=date(1990, 1, 1),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

    def test_invalid_nif_wrong_length(self):
        with pytest.raises(InvalidNIFError):
            PropertyOwner(
                id=uuid4(),
                property_id=uuid4(),
                full_name="Test",
                civil_status=CivilStatus.SINGLE,
                address="Test",
                nif="12345678",
                document_type=DocumentType.CARTAO_CIDADAO,
                document_id="12345678",
                issued_by="Test",
                issuing_district=None,
                date_of_birth=date(1990, 1, 1),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

    def test_civil_status_values(self):
        assert CivilStatus.SINGLE.value == "single"
        assert CivilStatus.MARRIED.value == "married"
        assert CivilStatus.DIVORCED.value == "divorced"
        assert CivilStatus.WIDOWED.value == "widowed"
        assert CivilStatus.CIVIL_UNION.value == "civil_union"
        assert CivilStatus.SEPARATED.value == "separated"

    def test_document_type_values(self):
        assert DocumentType.CARTAO_CIDADAO.value == "cartao_cidadao"
        assert DocumentType.PASSPORT.value == "passport"
