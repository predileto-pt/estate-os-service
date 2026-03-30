import pytest

from properties.domain.models.property_characteristics import PropertyCharacteristics


class TestPropertyCharacteristics:
    def test_create_with_defaults(self):
        chars = PropertyCharacteristics()
        assert chars.area_in_m2 is None
        assert chars.num_of_bedrooms is None

    def test_create_with_values(self):
        chars = PropertyCharacteristics(
            area_in_m2=100.5,
            num_of_bedrooms=3,
            num_of_bathrooms=2,
            built_at=2010,
            energy_rating="B",
            floor=2,
            parking_spaces=1,
            has_elevator=True,
            has_garden=False,
            has_pool=True,
        )
        assert chars.area_in_m2 == 100.5
        assert chars.num_of_bedrooms == 3
        assert chars.has_pool is True

    def test_frozen(self):
        chars = PropertyCharacteristics(area_in_m2=50.0)
        with pytest.raises(AttributeError):
            chars.area_in_m2 = 100.0  # type: ignore[misc]

    def test_negative_area_raises(self):
        with pytest.raises(ValueError, match="area_in_m2 must be positive"):
            PropertyCharacteristics(area_in_m2=-10.0)

    def test_zero_area_raises(self):
        with pytest.raises(ValueError, match="area_in_m2 must be positive"):
            PropertyCharacteristics(area_in_m2=0.0)

    def test_negative_bedrooms_raises(self):
        with pytest.raises(ValueError, match="num_of_bedrooms must be non-negative"):
            PropertyCharacteristics(num_of_bedrooms=-1)

    def test_negative_bathrooms_raises(self):
        with pytest.raises(ValueError, match="num_of_bathrooms must be non-negative"):
            PropertyCharacteristics(num_of_bathrooms=-1)

    def test_negative_parking_raises(self):
        with pytest.raises(ValueError, match="parking_spaces must be non-negative"):
            PropertyCharacteristics(parking_spaces=-1)

    def test_invalid_year_raises(self):
        with pytest.raises(ValueError, match="built_at must be a valid year"):
            PropertyCharacteristics(built_at=500)

    def test_to_dict(self):
        chars = PropertyCharacteristics(area_in_m2=85.0, num_of_bedrooms=2)
        d = chars.to_dict()
        assert d["area_in_m2"] == 85.0
        assert d["num_of_bedrooms"] == 2
        assert d["has_pool"] is None

    def test_from_dict(self):
        data = {"area_in_m2": 120.0, "energy_rating": "A+"}
        chars = PropertyCharacteristics.from_dict(data)
        assert chars.area_in_m2 == 120.0
        assert chars.energy_rating == "A+"
        assert chars.num_of_bedrooms is None

    def test_roundtrip(self):
        original = PropertyCharacteristics(area_in_m2=90.0, num_of_bedrooms=3, has_elevator=True)
        restored = PropertyCharacteristics.from_dict(original.to_dict())
        assert restored == original
