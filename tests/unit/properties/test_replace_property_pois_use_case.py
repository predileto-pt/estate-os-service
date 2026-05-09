"""Unit tests for `ReplacePropertyPois` — replace-all semantics.

Exercises the inline org-scope check, manually_edited flag enforcement,
aggregate_version bump, and replace-all semantics (including the
empty-list case which clears the catalog).
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from properties.adapters.inmemory.inmemory_property_poi_repo import (
    InMemoryPropertyPoiRepository,
)
from properties.adapters.inmemory.inmemory_property_repo import InMemoryPropertyRepository
from properties.application.use_cases.replace_property_pois import (
    PoiInput,
    ReplacePropertyPois,
)
from properties.domain.exceptions import PropertyNotFoundError
from properties.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)
from properties.domain.models.property_poi import PoiCategory

ORG_ID = UUID("00000000-0000-0000-0000-000000000010")
OTHER_ORG_ID = UUID("00000000-0000-0000-0000-000000000099")


def _property(*, organization_id: UUID = ORG_ID) -> Property:
    now = datetime.now(timezone.utc)
    return Property(
        id=uuid4(),
        organization_id=organization_id,
        address="Rua A",
        listing_type=ListingType.SALE,
        typology=Typology.APARTMENT,
        status=PropertyStatus.DRAFT,
        description=None,
        created_at=now,
        updated_at=now,
    )


def _input(category: PoiCategory = PoiCategory.GROCERY, name: str = "Pingo Doce") -> PoiInput:
    return PoiInput(
        category=category,
        name=name,
        distance_meters=200.0,
        latitude=38.768,
        longitude=-9.108,
    )


@pytest.fixture
def property_repo() -> InMemoryPropertyRepository:
    return InMemoryPropertyRepository()


@pytest.fixture
def property_poi_repo() -> InMemoryPropertyPoiRepository:
    return InMemoryPropertyPoiRepository()


async def test_happy_path_persists_and_marks_manually_edited(property_repo, property_poi_repo):
    prop = _property()
    await property_repo.save(prop)
    version_before = prop.aggregate_version

    use_case = ReplacePropertyPois(property_repo=property_repo, property_poi_repo=property_poi_repo)
    persisted = await use_case.execute(
        property_id=prop.id,
        organization_id=ORG_ID,
        pois=[_input(name="Pingo Doce"), _input(name="Lidl", category=PoiCategory.GROCERY)],
    )

    assert len(persisted) == 2
    assert all(p.manually_edited is True for p in persisted)
    assert all(p.property_id == prop.id for p in persisted)

    stored = await property_poi_repo.list_by_property(prop.id)
    assert len(stored) == 2

    refreshed = await property_repo.get_by_id(prop.id)
    assert refreshed.aggregate_version == version_before + 1


async def test_replace_clears_existing(property_repo, property_poi_repo):
    """Calling twice — second call's rows are the only ones left."""
    prop = _property()
    await property_repo.save(prop)
    use_case = ReplacePropertyPois(property_repo=property_repo, property_poi_repo=property_poi_repo)

    await use_case.execute(
        property_id=prop.id,
        organization_id=ORG_ID,
        pois=[_input(name="First"), _input(name="Second")],
    )
    second_persisted = await use_case.execute(
        property_id=prop.id, organization_id=ORG_ID, pois=[_input(name="Third")]
    )

    stored = await property_poi_repo.list_by_property(prop.id)
    assert {p.name for p in stored} == {"Third"}
    assert {p.id for p in stored} == {p.id for p in second_persisted}


async def test_empty_list_clears_catalog(property_repo, property_poi_repo):
    """`pois: []` is valid — clears the property's POI catalog."""
    prop = _property()
    await property_repo.save(prop)
    use_case = ReplacePropertyPois(property_repo=property_repo, property_poi_repo=property_poi_repo)

    # Seed first.
    await use_case.execute(
        property_id=prop.id, organization_id=ORG_ID, pois=[_input(name="To be cleared")]
    )
    # Then clear.
    persisted = await use_case.execute(property_id=prop.id, organization_id=ORG_ID, pois=[])

    assert persisted == []
    assert await property_poi_repo.list_by_property(prop.id) == []


async def test_unknown_property_raises_not_found(property_repo, property_poi_repo):
    use_case = ReplacePropertyPois(property_repo=property_repo, property_poi_repo=property_poi_repo)
    with pytest.raises(PropertyNotFoundError):
        await use_case.execute(property_id=uuid4(), organization_id=ORG_ID, pois=[_input()])


async def test_cross_org_collapses_to_not_found(property_repo, property_poi_repo):
    """Caller is a member of OTHER_ORG_ID; property belongs to ORG_ID.
    Use case raises PropertyNotFoundError before any write."""

    class TrackingRepo(InMemoryPropertyPoiRepository):
        def __init__(self) -> None:
            super().__init__()
            self.replace_calls = 0

        async def replace_for_property(self, *, property_id, pois):
            self.replace_calls += 1
            return await super().replace_for_property(property_id=property_id, pois=pois)

    tracking = TrackingRepo()
    prop = _property(organization_id=ORG_ID)
    await property_repo.save(prop)

    use_case = ReplacePropertyPois(property_repo=property_repo, property_poi_repo=tracking)
    with pytest.raises(PropertyNotFoundError):
        await use_case.execute(property_id=prop.id, organization_id=OTHER_ORG_ID, pois=[_input()])

    assert tracking.replace_calls == 0
