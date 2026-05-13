"""Unit tests for `UpdatePropertyCharacteristics` — partial-update use case
that merges the supplied fields onto the property's current characteristics.

Covers:
- Setting area_in_m2 on a property with no prior characteristics.
- Patching only one field while preserving the others.
- Clearing a field with explicit `None`.
- No-op short-circuit when merged value equals current.
- Org-scope check.
- Domain validation surfacing (e.g. non-positive area).
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from properties.adapters.inmemory.inmemory_property_repo import InMemoryPropertyRepository
from properties.application.events.property_event import build_property_snapshot
from properties.application.use_cases.update_property_characteristics import (
    UpdatePropertyCharacteristics,
)
from properties.domain.exceptions import PropertyNotFoundError
from properties.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)
from properties.domain.models.property_characteristics import PropertyCharacteristics
from shared.events.adapters.inmemory_event_bus import InMemoryEventPublisher
from shared.events.types import PROPERTY_UPDATED_V1

ORG_ID = UUID("00000000-0000-0000-0000-000000000010")
OTHER_ORG_ID = UUID("00000000-0000-0000-0000-000000000099")


def _property(
    *,
    organization_id: UUID = ORG_ID,
    typology: Typology = Typology.LAND,
    characteristics: PropertyCharacteristics | None = None,
) -> Property:
    now = datetime.now(timezone.utc)
    prop = Property(
        id=uuid4(),
        organization_id=organization_id,
        title="Land",
        address="Rua Original 1",
        listing_type=ListingType.SALE,
        typology=typology,
        status=PropertyStatus.DRAFT,
        description=None,
        characteristics=characteristics,
        created_at=now,
        updated_at=now,
    )
    prop.bump_version()
    return prop


@pytest.fixture
def repo() -> InMemoryPropertyRepository:
    return InMemoryPropertyRepository()


@pytest.fixture
def publisher() -> InMemoryEventPublisher:
    return InMemoryEventPublisher()


async def test_sets_area_when_no_characteristics_exist(repo, publisher):
    prop = _property(characteristics=None)
    await repo.save(prop)
    version_before = prop.aggregate_version

    use_case = UpdatePropertyCharacteristics(
        property_repo=repo, domain_event_publisher=publisher
    )
    refreshed = await use_case.execute(
        property_id=prop.id, organization_id=ORG_ID, area_in_m2=850.5
    )

    assert refreshed.characteristics is not None
    assert refreshed.characteristics.area_in_m2 == 850.5
    assert refreshed.aggregate_version == version_before + 1

    assert len(publisher.published) == 1
    event = publisher.published[0]
    assert event.event_type == PROPERTY_UPDATED_V1
    assert event.data == build_property_snapshot(refreshed)


async def test_partial_patch_preserves_other_fields(repo, publisher):
    initial = PropertyCharacteristics(area_in_m2=100, num_of_bedrooms=3, has_pool=True)
    prop = _property(typology=Typology.HOUSE, characteristics=initial)
    await repo.save(prop)

    use_case = UpdatePropertyCharacteristics(
        property_repo=repo, domain_event_publisher=publisher
    )
    refreshed = await use_case.execute(
        property_id=prop.id, organization_id=ORG_ID, area_in_m2=120
    )

    assert refreshed.characteristics.area_in_m2 == 120
    assert refreshed.characteristics.num_of_bedrooms == 3
    assert refreshed.characteristics.has_pool is True


async def test_explicit_none_clears_field(repo, publisher):
    initial = PropertyCharacteristics(area_in_m2=100, num_of_bedrooms=3)
    prop = _property(typology=Typology.HOUSE, characteristics=initial)
    await repo.save(prop)

    use_case = UpdatePropertyCharacteristics(
        property_repo=repo, domain_event_publisher=publisher
    )
    refreshed = await use_case.execute(
        property_id=prop.id, organization_id=ORG_ID, num_of_bedrooms=None
    )

    assert refreshed.characteristics.area_in_m2 == 100
    assert refreshed.characteristics.num_of_bedrooms is None


async def test_no_op_when_value_unchanged(repo, publisher):
    initial = PropertyCharacteristics(area_in_m2=850)
    prop = _property(characteristics=initial)
    await repo.save(prop)
    version_before = prop.aggregate_version

    use_case = UpdatePropertyCharacteristics(
        property_repo=repo, domain_event_publisher=publisher
    )
    refreshed = await use_case.execute(
        property_id=prop.id, organization_id=ORG_ID, area_in_m2=850
    )

    assert refreshed.aggregate_version == version_before
    assert publisher.published == []


async def test_unknown_id_raises_not_found(repo, publisher):
    use_case = UpdatePropertyCharacteristics(
        property_repo=repo, domain_event_publisher=publisher
    )
    with pytest.raises(PropertyNotFoundError):
        await use_case.execute(
            property_id=uuid4(), organization_id=ORG_ID, area_in_m2=100
        )
    assert publisher.published == []


async def test_wrong_org_collapses_to_not_found(repo, publisher):
    prop = _property(organization_id=ORG_ID)
    await repo.save(prop)

    use_case = UpdatePropertyCharacteristics(
        property_repo=repo, domain_event_publisher=publisher
    )
    with pytest.raises(PropertyNotFoundError):
        await use_case.execute(
            property_id=prop.id, organization_id=OTHER_ORG_ID, area_in_m2=100
        )
    assert publisher.published == []


async def test_invalid_area_raises_value_error(repo, publisher):
    prop = _property(characteristics=None)
    await repo.save(prop)

    use_case = UpdatePropertyCharacteristics(
        property_repo=repo, domain_event_publisher=publisher
    )
    with pytest.raises(ValueError):
        await use_case.execute(
            property_id=prop.id, organization_id=ORG_ID, area_in_m2=-5
        )

    stored = await repo.get_by_id(prop.id)
    assert stored.characteristics is None
    assert publisher.published == []


async def test_no_publisher_wired_is_fine(repo):
    prop = _property(characteristics=None)
    await repo.save(prop)

    use_case = UpdatePropertyCharacteristics(
        property_repo=repo, domain_event_publisher=None
    )
    refreshed = await use_case.execute(
        property_id=prop.id, organization_id=ORG_ID, area_in_m2=420
    )
    assert refreshed.characteristics.area_in_m2 == 420
