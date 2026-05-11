"""Unit tests for `UnpublishProperty` — symmetric to PublishProperty.

Covers:
- Happy path: ACTIVE → DRAFT, version bumped, PROPERTY_UNPUBLISHED.v1
  emitted with the minimal {id, organization_id, aggregate_version}
  payload.
- Org-scope check collapses cross-org to PropertyNotFoundError.
- Unknown id raises PropertyNotFoundError.
- Non-ACTIVE status (DRAFT / WITHDRAWN / SOLD / RENTED) raises
  PropertyNotUnpublishableError; no event emitted.
- Publish-failure is log-and-swallowed.
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from properties.adapters.inmemory.inmemory_property_repo import InMemoryPropertyRepository
from properties.application.use_cases.unpublish_property import UnpublishProperty
from properties.domain.exceptions import (
    PropertyNotFoundError,
    PropertyNotUnpublishableError,
)
from properties.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)
from shared.events.adapters.inmemory_event_bus import InMemoryEventPublisher
from shared.events.types import PROPERTY_UNPUBLISHED_V1

ORG_ID = UUID("00000000-0000-0000-0000-000000000010")
OTHER_ORG_ID = UUID("00000000-0000-0000-0000-000000000099")


def _prop(
    *, status: PropertyStatus = PropertyStatus.ACTIVE, organization_id: UUID = ORG_ID
) -> Property:
    now = datetime.now(timezone.utc)
    return Property(
        id=uuid4(),
        organization_id=organization_id,
        title="Test property",
        address="Rua Augusta 1, Lisboa",
        listing_type=ListingType.SALE,
        typology=Typology.APARTMENT,
        status=status,
        description=None,
        created_at=now,
        updated_at=now,
        aggregate_version=2,  # already published once
    )


@pytest.fixture
def repo() -> InMemoryPropertyRepository:
    return InMemoryPropertyRepository()


@pytest.fixture
def publisher() -> InMemoryEventPublisher:
    return InMemoryEventPublisher()


async def test_happy_path_active_to_draft_emits_unpublished(repo, publisher):
    prop = _prop()
    await repo.save(prop)
    version_before = prop.aggregate_version

    use_case = UnpublishProperty(property_repo=repo, domain_event_publisher=publisher)
    refreshed = await use_case.execute(property_id=prop.id, organization_id=ORG_ID)

    # Status flipped, version bumped.
    assert refreshed.status == PropertyStatus.DRAFT
    assert refreshed.aggregate_version == version_before + 1

    stored = await repo.get_by_id(prop.id)
    assert stored.status == PropertyStatus.DRAFT
    assert stored.aggregate_version == version_before + 1

    # Minimal payload — projector deletes by id + version guard.
    assert len(publisher.published) == 1
    event = publisher.published[0]
    assert event.event_type == PROPERTY_UNPUBLISHED_V1
    assert event.data == {
        "id": str(prop.id),
        "organization_id": str(ORG_ID),
        "aggregate_version": version_before + 1,
    }


async def test_unknown_id_raises_not_found(repo, publisher):
    use_case = UnpublishProperty(property_repo=repo, domain_event_publisher=publisher)
    with pytest.raises(PropertyNotFoundError):
        await use_case.execute(property_id=uuid4(), organization_id=ORG_ID)
    assert publisher.published == []


async def test_wrong_org_collapses_to_not_found(repo, publisher):
    prop = _prop(organization_id=ORG_ID)
    await repo.save(prop)

    use_case = UnpublishProperty(property_repo=repo, domain_event_publisher=publisher)
    with pytest.raises(PropertyNotFoundError):
        await use_case.execute(property_id=prop.id, organization_id=OTHER_ORG_ID)
    assert publisher.published == []


@pytest.mark.parametrize(
    "status",
    [
        PropertyStatus.DRAFT,
        PropertyStatus.WITHDRAWN,
        PropertyStatus.SOLD,
        PropertyStatus.RENTED,
    ],
)
async def test_non_active_status_raises_with_reason(repo, publisher, status):
    prop = _prop(status=status)
    await repo.save(prop)

    use_case = UnpublishProperty(property_repo=repo, domain_event_publisher=publisher)
    with pytest.raises(PropertyNotUnpublishableError) as exc:
        await use_case.execute(property_id=prop.id, organization_id=ORG_ID)
    assert exc.value.reasons == [f"cannot_unpublish_from_status:{status.value}"]

    stored = await repo.get_by_id(prop.id)
    assert stored.status == status  # unchanged
    assert publisher.published == []


async def test_publish_failure_is_swallowed(repo):
    prop = _prop()
    await repo.save(prop)

    class BrokenPublisher:
        async def publish(self, _event):
            raise RuntimeError("SNS is down")

    use_case = UnpublishProperty(property_repo=repo, domain_event_publisher=BrokenPublisher())
    refreshed = await use_case.execute(property_id=prop.id, organization_id=ORG_ID)

    assert refreshed.status == PropertyStatus.DRAFT
    stored = await repo.get_by_id(prop.id)
    assert stored.status == PropertyStatus.DRAFT


async def test_no_publisher_wired_is_fine(repo):
    prop = _prop()
    await repo.save(prop)

    use_case = UnpublishProperty(property_repo=repo, domain_event_publisher=None)
    refreshed = await use_case.execute(property_id=prop.id, organization_id=ORG_ID)
    assert refreshed.status == PropertyStatus.DRAFT
