import pytest
from datetime import datetime, timezone
from uuid import UUID, uuid4

from properties.adapters.inmemory.inmemory_places_service import (
    InMemoryPlacesService,
)
from properties.adapters.inmemory.inmemory_property_amenity_repo import (
    InMemoryPropertyAmenityRepository,
)
from properties.adapters.inmemory.inmemory_property_repo import (
    InMemoryPropertyRepository,
)
from properties.application.use_cases.discover_property_amenities import (
    DiscoverPropertyAmenities,
)
from properties.domain.exceptions import (
    PropertyMissingCoordinatesError,
    PropertyNotFoundError,
)
from properties.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)
from properties.domain.models.nearby_place import NearbyPlace
from properties.domain.models.property_amenity import AmenityCategory

TEST_ORG_ID = UUID("00000000-0000-0000-0000-000000000010")


def _make_property(
    lat: float | None = 38.7223,
    lng: float | None = -9.1393,
    property_id: UUID | None = None,
) -> Property:
    now = datetime.now(timezone.utc)
    return Property(
        id=property_id or uuid4(),
        organization_id=TEST_ORG_ID,
        address="Rua Augusta 100, 1100-053 Lisboa",
        listing_type=ListingType.SALE,
        typology=Typology.APARTMENT,
        status=PropertyStatus.DRAFT,
        description=None,
        latitude=lat,
        longitude=lng,
        created_at=now,
        updated_at=now,
    )


def _make_place(name: str, distance: float) -> NearbyPlace:
    return NearbyPlace(
        name=name,
        distance_meters=distance,
        latitude=38.72,
        longitude=-9.14,
    )


@pytest.fixture
def prop_repo():
    return InMemoryPropertyRepository()


@pytest.fixture
def places_service():
    return InMemoryPlacesService()


@pytest.fixture
def amenity_repo():
    return InMemoryPropertyAmenityRepository()


@pytest.fixture
def use_case(prop_repo, places_service, amenity_repo):
    return DiscoverPropertyAmenities(
        property_repo=prop_repo,
        places_service=places_service,
        amenity_repo=amenity_repo,
    )


class TestDiscoverPropertyAmenities:
    async def test_happy_path(self, use_case, prop_repo, places_service, amenity_repo):
        prop = _make_property()
        await prop_repo.save(prop)

        # Set up results for a few categories
        places_service.set_results(
            "hospital",
            [
                _make_place("Hospital Santa Maria", 800.0),
                _make_place("Hospital São José", 1200.0),
            ],
        )
        places_service.set_results(
            "bank",
            [
                _make_place("Millennium BCP", 200.0),
            ],
        )

        result = await use_case.execute(property_id=str(prop.id))

        # Should have amenities for hospital and bank (others return empty)
        categories = {a.category for a in result}
        assert AmenityCategory.HOSPITAL in categories
        assert AmenityCategory.BANK in categories

        hospital = next(a for a in result if a.category == AmenityCategory.HOSPITAL)
        assert hospital.nearest_name == "Hospital Santa Maria"
        assert hospital.nearest_distance_meters == 800.0
        assert hospital.total_count == 2

        bank = next(a for a in result if a.category == AmenityCategory.BANK)
        assert bank.nearest_name == "Millennium BCP"
        assert bank.total_count == 1

    async def test_property_not_found(self, use_case):
        with pytest.raises(PropertyNotFoundError):
            await use_case.execute(property_id=str(uuid4()))

    async def test_property_missing_coordinates(self, use_case, prop_repo):
        prop = _make_property(lat=None, lng=None)
        await prop_repo.save(prop)

        with pytest.raises(PropertyMissingCoordinatesError):
            await use_case.execute(property_id=str(prop.id))

    async def test_empty_results_skips_category(self, use_case, prop_repo, places_service):
        prop = _make_property()
        await prop_repo.save(prop)
        # No results configured — all categories return empty

        result = await use_case.execute(property_id=str(prop.id))
        assert len(result) == 0

    async def test_grocery_aggregation(self, use_case, prop_repo, places_service):
        prop = _make_property()
        await prop_repo.save(prop)

        places_service.set_results(
            "supermarket:Continente",
            [
                _make_place("Continente Bom Dia", 500.0),
            ],
        )
        places_service.set_results(
            "supermarket:Lidl",
            [
                _make_place("Lidl Baixa", 300.0),
            ],
        )
        places_service.set_results(
            "supermarket:Pingo Doce",
            [
                _make_place("Pingo Doce Express", 700.0),
            ],
        )
        places_service.set_results(
            "supermarket",
            [
                _make_place("Lidl Baixa", 300.0),  # duplicate
                _make_place("Mini Preço", 900.0),
            ],
        )

        result = await use_case.execute(property_id=str(prop.id))

        grocery = next(a for a in result if a.category == AmenityCategory.GROCERY)
        # Nearest should be Lidl at 300m
        assert grocery.nearest_name == "Lidl Baixa"
        assert grocery.nearest_distance_meters == 300.0
        # Total unique: Continente, Lidl, Pingo Doce, Mini Preço = 4
        assert grocery.total_count == 4

    async def test_idempotent_rerun(self, use_case, prop_repo, places_service, amenity_repo):
        prop = _make_property()
        await prop_repo.save(prop)

        places_service.set_results(
            "hospital",
            [
                _make_place("Hospital A", 500.0),
            ],
        )

        # Run first time
        await use_case.execute(property_id=str(prop.id))
        first_results = await amenity_repo.get_by_property_id(prop.id)
        assert len([a for a in first_results if a.category == AmenityCategory.HOSPITAL]) == 1

        # Run second time — should replace, not duplicate
        await use_case.execute(property_id=str(prop.id))
        second_results = await amenity_repo.get_by_property_id(prop.id)
        assert len([a for a in second_results if a.category == AmenityCategory.HOSPITAL]) == 1

    async def test_places_service_error_handled_gracefully(self, prop_repo, amenity_repo):
        class FailingPlacesService(InMemoryPlacesService):
            async def find_nearby(self, *args, **kwargs):
                raise RuntimeError("API error")

        uc = DiscoverPropertyAmenities(
            property_repo=prop_repo,
            places_service=FailingPlacesService(),
            amenity_repo=amenity_repo,
        )

        prop = _make_property()
        await prop_repo.save(prop)

        result = await uc.execute(property_id=str(prop.id))
        # All categories fail but we get an empty list, no exception
        assert len(result) == 0
