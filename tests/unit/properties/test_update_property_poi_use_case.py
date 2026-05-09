"""Unit tests for `UpdatePropertyPoi` — PATCH semantics + cross-property defense."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from properties.adapters.inmemory.inmemory_property_poi_repo import (
    InMemoryPropertyPoiRepository,
)
from properties.adapters.inmemory.inmemory_property_repo import InMemoryPropertyRepository
from properties.application.use_cases.update_property_poi import (
    PoiPatch,
    UpdatePropertyPoi,
)
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
        address="Rua A",
        listing_type=ListingType.SALE,
        typology=Typology.APARTMENT,
        status=PropertyStatus.DRAFT,
        description=None,
        created_at=now,
        updated_at=now,
    )


def _poi(property_id: UUID, *, name: str = "Original") -> PropertyPoi:
    now = datetime.now(timezone.utc)
    return PropertyPoi(
        id=uuid4(),
        property_id=property_id,
        category=PoiCategory.SCHOOL,
        name=name,
        distance_meters=600.0,
        latitude=38.768,
        longitude=-9.108,
        manually_edited=False,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def property_repo() -> InMemoryPropertyRepository:
    return InMemoryPropertyRepository()


@pytest.fixture
def property_poi_repo() -> InMemoryPropertyPoiRepository:
    return InMemoryPropertyPoiRepository()


async def test_partial_patch_only_updates_specified_fields(property_repo, property_poi_repo):
    prop = _property()
    await property_repo.save(prop)
    poi = _poi(prop.id, name="Original Name")
    await property_poi_repo.replace_for_property(property_id=prop.id, pois=[poi])
    seeded = (await property_poi_repo.list_by_property(prop.id))[0]
    version_before = prop.aggregate_version

    use_case = UpdatePropertyPoi(property_repo=property_repo, property_poi_repo=property_poi_repo)
    updated = await use_case.execute(
        property_id=prop.id,
        organization_id=ORG_ID,
        poi_id=seeded.id,
        patch=PoiPatch(distance_meters=320.0),
    )

    assert updated.distance_meters == 320.0
    assert updated.name == "Original Name"  # unchanged
    assert updated.category == PoiCategory.SCHOOL  # unchanged
    assert updated.latitude == 38.768  # unchanged
    assert updated.manually_edited is True  # always set on PATCH

    refreshed = await property_repo.get_by_id(prop.id)
    assert refreshed.aggregate_version == version_before + 1


async def test_metadata_round_trip(property_repo, property_poi_repo):
    prop = _property()
    await property_repo.save(prop)
    poi = _poi(prop.id)
    await property_poi_repo.replace_for_property(property_id=prop.id, pois=[poi])
    seeded = (await property_poi_repo.list_by_property(prop.id))[0]

    use_case = UpdatePropertyPoi(property_repo=property_repo, property_poi_repo=property_poi_repo)
    updated = await use_case.execute(
        property_id=prop.id,
        organization_id=ORG_ID,
        poi_id=seeded.id,
        patch=PoiPatch(metadata={"rating": 4.2, "notes": "agent confirmed"}),
    )
    assert updated.metadata == {"rating": 4.2, "notes": "agent confirmed"}


async def test_cross_property_id_returns_not_found(property_repo, property_poi_repo):
    """POI exists but belongs to a different property than the URL says — 404."""
    prop_a = _property()
    prop_b = _property()
    await property_repo.save(prop_a)
    await property_repo.save(prop_b)

    poi_under_b = _poi(prop_b.id, name="Belongs to B")
    await property_poi_repo.replace_for_property(property_id=prop_b.id, pois=[poi_under_b])
    seeded_b = (await property_poi_repo.list_by_property(prop_b.id))[0]

    class TrackingRepo(InMemoryPropertyPoiRepository):
        def __init__(self) -> None:
            super().__init__()
            self.update_calls = 0
            for pid, p in property_poi_repo._pois.items():
                self._pois[pid] = p

        async def update(self, poi):
            self.update_calls += 1
            return await super().update(poi)

    tracking = TrackingRepo()
    use_case = UpdatePropertyPoi(property_repo=property_repo, property_poi_repo=tracking)

    # Caller addresses POI under prop_a, but seeded_b belongs to prop_b.
    with pytest.raises(PropertyNotFoundError):
        await use_case.execute(
            property_id=prop_a.id,
            organization_id=ORG_ID,
            poi_id=seeded_b.id,
            patch=PoiPatch(name="Hijack attempt"),
        )

    assert tracking.update_calls == 0


async def test_cross_org_collapses_to_not_found(property_repo, property_poi_repo):
    prop = _property(organization_id=ORG_ID)
    await property_repo.save(prop)
    poi = _poi(prop.id)
    await property_poi_repo.replace_for_property(property_id=prop.id, pois=[poi])
    seeded = (await property_poi_repo.list_by_property(prop.id))[0]

    use_case = UpdatePropertyPoi(property_repo=property_repo, property_poi_repo=property_poi_repo)
    with pytest.raises(PropertyNotFoundError):
        await use_case.execute(
            property_id=prop.id,
            organization_id=OTHER_ORG_ID,
            poi_id=seeded.id,
            patch=PoiPatch(name="x"),
        )
