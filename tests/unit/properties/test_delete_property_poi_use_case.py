"""Unit tests for `DeletePropertyPoi` — non-idempotent delete + defenses."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from properties.adapters.inmemory.inmemory_property_poi_repo import (
    InMemoryPropertyPoiRepository,
)
from properties.adapters.inmemory.inmemory_property_repo import InMemoryPropertyRepository
from properties.application.use_cases.delete_property_poi import DeletePropertyPoi
from properties.domain.exceptions import PropertyNotFoundError
from properties.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)
from properties.domain.models.property_poi import PoiCategory, PropertyPoi

ORG_ID = UUID("00000000-0000-0000-0000-000000000010")


def _property() -> Property:
    now = datetime.now(timezone.utc)
    return Property(
        id=uuid4(),
        organization_id=ORG_ID,
        title="Test property",
        address="Rua A",
        listing_type=ListingType.SALE,
        typology=Typology.APARTMENT,
        status=PropertyStatus.DRAFT,
        description=None,
        created_at=now,
        updated_at=now,
    )


def _poi(property_id: UUID) -> PropertyPoi:
    now = datetime.now(timezone.utc)
    return PropertyPoi(
        id=uuid4(),
        property_id=property_id,
        category=PoiCategory.GROCERY,
        name="Pingo Doce",
        distance_meters=200.0,
        latitude=38.768,
        longitude=-9.108,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def property_repo() -> InMemoryPropertyRepository:
    return InMemoryPropertyRepository()


@pytest.fixture
def property_poi_repo() -> InMemoryPropertyPoiRepository:
    return InMemoryPropertyPoiRepository()


async def test_happy_path_removes_and_bumps_version(property_repo, property_poi_repo):
    prop = _property()
    await property_repo.save(prop)
    poi = _poi(prop.id)
    await property_poi_repo.replace_for_property(property_id=prop.id, pois=[poi])
    seeded = (await property_poi_repo.list_by_property(prop.id))[0]
    version_before = prop.aggregate_version

    use_case = DeletePropertyPoi(property_repo=property_repo, property_poi_repo=property_poi_repo)
    await use_case.execute(property_id=prop.id, organization_id=ORG_ID, poi_id=seeded.id)

    assert await property_poi_repo.list_by_property(prop.id) == []
    refreshed = await property_repo.get_by_id(prop.id)
    assert refreshed.aggregate_version == version_before + 1


async def test_missing_poi_raises_not_found(property_repo, property_poi_repo):
    """Not idempotent — matches the `delete_property` precedent."""
    prop = _property()
    await property_repo.save(prop)

    use_case = DeletePropertyPoi(property_repo=property_repo, property_poi_repo=property_poi_repo)
    with pytest.raises(PropertyNotFoundError):
        await use_case.execute(property_id=prop.id, organization_id=ORG_ID, poi_id=uuid4())


async def test_cross_property_poi_id_returns_not_found(property_repo, property_poi_repo):
    prop_a = _property()
    prop_b = _property()
    await property_repo.save(prop_a)
    await property_repo.save(prop_b)

    poi_under_b = _poi(prop_b.id)
    await property_poi_repo.replace_for_property(property_id=prop_b.id, pois=[poi_under_b])
    seeded_b = (await property_poi_repo.list_by_property(prop_b.id))[0]

    use_case = DeletePropertyPoi(property_repo=property_repo, property_poi_repo=property_poi_repo)
    with pytest.raises(PropertyNotFoundError):
        await use_case.execute(property_id=prop_a.id, organization_id=ORG_ID, poi_id=seeded_b.id)

    # POI under B is still there.
    assert len(await property_poi_repo.list_by_property(prop_b.id)) == 1


async def test_missing_property_raises_not_found(property_repo, property_poi_repo):
    use_case = DeletePropertyPoi(property_repo=property_repo, property_poi_repo=property_poi_repo)
    with pytest.raises(PropertyNotFoundError):
        await use_case.execute(property_id=uuid4(), organization_id=ORG_ID, poi_id=uuid4())
