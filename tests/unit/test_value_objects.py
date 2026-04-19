import pytest

from organizations.domain.models.value_objects import Address, PhoneNumber


class TestPhoneNumber:
    def test_valid_phone(self):
        phone = PhoneNumber(country_code="+351", number="912345678")
        assert phone.country_code == "+351"
        assert phone.number == "912345678"

    def test_invalid_country_code(self):
        with pytest.raises(ValueError, match="Country code must start with"):
            PhoneNumber(country_code="351", number="912345678")

    def test_empty_number(self):
        with pytest.raises(ValueError, match="Phone number cannot be empty"):
            PhoneNumber(country_code="+351", number="  ")

    def test_frozen(self):
        phone = PhoneNumber(country_code="+351", number="912345678")
        with pytest.raises(AttributeError):
            phone.number = "999999999"


class TestAddress:
    def test_valid_address_pt(self):
        addr = Address(
            street="Rua Augusta 1",
            parish="Santa Maria Maior",
            municipality="Lisboa",
            district="Lisboa",
            postal_code="1100-048",
            country="PT",
        )
        assert addr.country == "PT"

    def test_valid_address_es(self):
        addr = Address(
            street="Gran Via 1",
            parish=None,
            municipality="Madrid",
            district="Madrid",
            postal_code="28013",
            country="ES",
        )
        assert addr.country == "ES"

    def test_invalid_country(self):
        with pytest.raises(ValueError, match="Country must be"):
            Address(
                street="123 Main St",
                parish=None,
                municipality=None,
                district=None,
                postal_code=None,
                country="US",
            )

    def test_frozen(self):
        addr = Address(
            street="Rua Augusta 1",
            parish=None,
            municipality=None,
            district=None,
            postal_code=None,
            country="PT",
        )
        with pytest.raises(AttributeError):
            addr.street = "New Street"
