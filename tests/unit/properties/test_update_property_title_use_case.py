"""Unit tests for `UpdatePropertyTitle` — mirrors UpdatePropertyAddress.

Covers happy path, no-op short-circuit, org-scope check, empty-title
validation, ACTIVE-property allowance, and graceful publisher failures.
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from properties.adapters.inmemory.inmemory_property_repo import InMemoryPropertyRepository
from properties.application.events.property_event import build_property_snapshot
from properties.application.use_cases.update_property_title import UpdatePropertyTitle
from properties.domain.exceptions import (
    PropertyNotFoundError,
    PropertyTitleInvalidError,
)
from properties.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)
from shared.events.adapters.inmemory_event_bus import InMemoryEventPublisher
from shared.events.types import PROPERTY_UPDATED_V1

ORG_ID = UUID("00000000-0000-0000-0000-000000000010")
OTHER_ORG_ID = UUID("00000000-0000-0000-0000-000000000099")


def _property(
    *,
    title: str = "Original title",
    organization_id: UUID = ORG_ID,
    status: PropertyStatus = PropertyStatus.DRAFT,
) -> Property:
    now = datetime.now(timezone.utc)
    prop = Property(
        id=uuid4(),
        organization_id=organization_id,
        title=title,
        address="Rua Original 1",
        listing_type=ListingType.SALE,
        typology=Typology.APARTMENT,
        status=status,
        description=None,
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


async def test_happy_path_persists_bumps_emits(repo, publisher):
    prop = _property(title="Old title")
    await repo.save(prop)
    version_before = prop.aggregate_version

    use_case = UpdatePropertyTitle(property_repo=repo, domain_event_publisher=publisher)
    refreshed = await use_case.execute(
        property_id=prop.id, organization_id=ORG_ID, title="Polished marketing title"
    )

    assert refreshed.title == "Polished marketing title"
    assert refreshed.aggregate_version == version_before + 1

    stored = await repo.get_by_id(prop.id)
    assert stored.title == "Polished marketing title"
    assert stored.aggregate_version == version_before + 1

    assert len(publisher.published) == 1
    event = publisher.published[0]
    assert event.event_type == PROPERTY_UPDATED_V1
    assert event.data == build_property_snapshot(refreshed)
    assert event.data["title"] == "Polished marketing title"
    assert event.data["aggregate_version"] == version_before + 1


async def test_strips_surrounding_whitespace(repo, publisher):
    prop = _property(title="Old")
    await repo.save(prop)

    use_case = UpdatePropertyTitle(property_repo=repo, domain_event_publisher=publisher)
    refreshed = await use_case.execute(
        property_id=prop.id, organization_id=ORG_ID, title="  Shiny title  "
    )

    assert refreshed.title == "Shiny title"
    stored = await repo.get_by_id(prop.id)
    assert stored.title == "Shiny title"


async def test_no_op_when_value_unchanged(repo, publisher):
    prop = _property(title="Same title")
    await repo.save(prop)
    version_before = prop.aggregate_version

    use_case = UpdatePropertyTitle(property_repo=repo, domain_event_publisher=publisher)
    refreshed = await use_case.execute(
        property_id=prop.id, organization_id=ORG_ID, title="Same title"
    )

    assert refreshed.title == "Same title"
    assert refreshed.aggregate_version == version_before
    assert publisher.published == []


async def test_no_op_when_only_whitespace_differs(repo, publisher):
    prop = _property(title="Same title")
    await repo.save(prop)
    version_before = prop.aggregate_version

    use_case = UpdatePropertyTitle(property_repo=repo, domain_event_publisher=publisher)
    refreshed = await use_case.execute(
        property_id=prop.id, organization_id=ORG_ID, title="  Same title  "
    )

    assert refreshed.aggregate_version == version_before
    assert publisher.published == []


async def test_unknown_id_raises_not_found(repo, publisher):
    use_case = UpdatePropertyTitle(property_repo=repo, domain_event_publisher=publisher)
    with pytest.raises(PropertyNotFoundError):
        await use_case.execute(property_id=uuid4(), organization_id=ORG_ID, title="New")
    assert publisher.published == []


async def test_wrong_org_collapses_to_not_found(publisher):
    class TrackingRepo(InMemoryPropertyRepository):
        def __init__(self) -> None:
            super().__init__()
            self.update_title_calls = 0
            self.bump_calls = 0

        async def update_title(self, property_id, title):
            self.update_title_calls += 1
            await super().update_title(property_id, title)

        async def bump_aggregate_version(self, property_id):
            self.bump_calls += 1
            return await super().bump_aggregate_version(property_id)

    tracking_repo = TrackingRepo()
    prop = _property(organization_id=ORG_ID, title="Original")
    await tracking_repo.save(prop)

    use_case = UpdatePropertyTitle(
        property_repo=tracking_repo, domain_event_publisher=publisher
    )
    with pytest.raises(PropertyNotFoundError):
        await use_case.execute(property_id=prop.id, organization_id=OTHER_ORG_ID, title="New")

    assert tracking_repo.update_title_calls == 0
    assert tracking_repo.bump_calls == 0
    assert publisher.published == []
    stored = await tracking_repo.get_by_id(prop.id)
    assert stored.title == "Original"


async def test_empty_title_raises_invalid(repo, publisher):
    prop = _property(title="Original")
    await repo.save(prop)

    use_case = UpdatePropertyTitle(property_repo=repo, domain_event_publisher=publisher)
    with pytest.raises(PropertyTitleInvalidError):
        await use_case.execute(property_id=prop.id, organization_id=ORG_ID, title="   ")

    stored = await repo.get_by_id(prop.id)
    assert stored.title == "Original"
    assert publisher.published == []


async def test_works_for_active_property(repo, publisher):
    prop = _property(title="Old", status=PropertyStatus.ACTIVE)
    await repo.save(prop)

    use_case = UpdatePropertyTitle(property_repo=repo, domain_event_publisher=publisher)
    refreshed = await use_case.execute(
        property_id=prop.id, organization_id=ORG_ID, title="New title"
    )

    assert refreshed.status == PropertyStatus.ACTIVE
    assert refreshed.title == "New title"
    assert publisher.published[0].event_type == PROPERTY_UPDATED_V1


async def test_publish_failure_is_swallowed(repo):
    prop = _property(title="Old")
    await repo.save(prop)

    class BrokenPublisher:
        async def publish(self, _event):
            raise RuntimeError("SNS is down")

    use_case = UpdatePropertyTitle(
        property_repo=repo, domain_event_publisher=BrokenPublisher()
    )
    refreshed = await use_case.execute(
        property_id=prop.id, organization_id=ORG_ID, title="New title"
    )

    assert refreshed.title == "New title"
    stored = await repo.get_by_id(prop.id)
    assert stored.title == "New title"


async def test_no_publisher_wired_is_fine(repo):
    prop = _property(title="Old")
    await repo.save(prop)

    use_case = UpdatePropertyTitle(property_repo=repo, domain_event_publisher=None)
    refreshed = await use_case.execute(
        property_id=prop.id, organization_id=ORG_ID, title="New title"
    )

    assert refreshed.title == "New title"
