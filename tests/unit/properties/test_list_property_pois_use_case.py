"""Unit tests for `ListPropertyPois` — read-only with cross-org defense."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from properties.adapters.inmemory.inmemory_property_poi_repo import (
    InMemoryPropertyPoiRepository,
)
from properties.adapters.inmemory.inmemory_property_repo import InMemoryPropertyRepository
from properties.application.use_cases.list_property_pois import ListPropertyPois
from properties.domain.exceptions import PropertyNotFoundError
from properties.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)
from properties.domain.models.property_poi import PoiCategory, PropertyPoi

ORG_ID = UUID("00000000-0000-0000-0000-000000000010")
OTHER_ORG_ID = UUID("00000000-0000-0000-0000-000000000099")


def _property(*, organization_id: UUID = ORG_ID) -> Property:
    now = datetime.now(timezone.utc)
    return Property(
        id=uuid4(),
        organization_id=organization_id,
        title="Test property",
        address="Rua A",
        listing_type=ListingType.SALE,
        typology=Typology.APARTMENT,
        status=PropertyStatus.DRAFT,
        description=None,
        created_at=now,
        updated_at=now,
    )


def _poi(property_id: UUID, name: str = "POI") -> PropertyPoi:
    now = datetime.now(timezone.utc)
    return PropertyPoi(
        id=uuid4(),
        property_id=property_id,
        category=PoiCategory.GROCERY,
        name=name,
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


async def test_happy_path_returns_list(property_repo, property_poi_repo):
    prop = _property()
    await property_repo.save(prop)
    await property_poi_repo.replace_for_property(
        property_id=prop.id,
        pois=[_poi(prop.id, "First"), _poi(prop.id, "Second")],
    )

    use_case = ListPropertyPois(property_repo=property_repo, property_poi_repo=property_poi_repo)
    result = await use_case.execute(property_id=prop.id, organization_id=ORG_ID)
    assert {p.name for p in result} == {"First", "Second"}


async def test_empty_returns_empty_list(property_repo, property_poi_repo):
    prop = _property()
    await property_repo.save(prop)

    use_case = ListPropertyPois(property_repo=property_repo, property_poi_repo=property_poi_repo)
    result = await use_case.execute(property_id=prop.id, organization_id=ORG_ID)
    assert result == []


async def test_unknown_property_raises_not_found(property_repo, property_poi_repo):
    use_case = ListPropertyPois(property_repo=property_repo, property_poi_repo=property_poi_repo)
    with pytest.raises(PropertyNotFoundError):
        await use_case.execute(property_id=uuid4(), organization_id=ORG_ID)


async def test_cross_org_collapses_to_not_found(property_repo, property_poi_repo):
    prop = _property(organization_id=ORG_ID)
    await property_repo.save(prop)

    use_case = ListPropertyPois(property_repo=property_repo, property_poi_repo=property_poi_repo)
    with pytest.raises(PropertyNotFoundError):
        await use_case.execute(property_id=prop.id, organization_id=OTHER_ORG_ID)
