"""Unit tests for `PublishProperty` — the orchestration around `Property.publish()`.

Covers:
- Happy path: persists, bumps version, emits PROPERTY_PUBLISHED.v1 with the
  build_property_snapshot payload, returns the refreshed aggregate.
- Org-scope check: wrong or missing org collapses to PropertyNotFoundError.
- Domain gaps bubble PropertyNotPublishableError and no event is emitted.
- Publish-failure is log-and-swallowed — the use case still returns success
  because persistence has already committed.
"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from properties.adapters.inmemory.inmemory_property_repo import InMemoryPropertyRepository
from properties.application.events.property_event import build_property_snapshot
from properties.application.use_cases.publish_property import PublishProperty
from properties.domain.exceptions import (
    PropertyNotFoundError,
    PropertyNotPublishableError,
)
from properties.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)
from properties.domain.models.property_image import PropertyImage
from properties.domain.models.property_owner import PropertyOwner
from properties.domain.models.property_price import PropertyPrice
from shared.events.adapters.inmemory_event_bus import InMemoryEventPublisher
from shared.events.types import PROPERTY_PUBLISHED_V1

ORG_ID = UUID("00000000-0000-0000-0000-000000000010")
OTHER_ORG_ID = UUID("00000000-0000-0000-0000-000000000099")


def _complete_property(
    *, status: PropertyStatus = PropertyStatus.DRAFT, organization_id: UUID = ORG_ID
) -> Property:
    now = datetime.now(timezone.utc)
    pid = uuid4()
    prop = Property(
        id=pid,
        organization_id=organization_id,
        address="Rua Augusta 1, Lisboa",
        listing_type=ListingType.SALE,
        typology=Typology.APARTMENT,
        status=status,
        description=None,
        created_at=now,
        updated_at=now,
    )
    prop.add_owner(
        PropertyOwner(
            id=uuid4(),
            property_id=pid,
            full_name="Maria Silva",
            civil_status=None,
            address="Rua Augusta 1",
            nif="123456789",
            document_type=None,
            document_id=None,
            issued_by=None,
            issuing_district=None,
            date_of_birth=None,
            created_at=now,
            updated_at=now,
        )
    )
    prop.add_price(
        PropertyPrice(
            id=uuid4(),
            property_id=pid,
            amount=Decimal("350000.00"),
            listing_type=ListingType.SALE,
            created_at=now,
            updated_at=now,
        )
    )
    prop.add_image(
        PropertyImage(
            id=uuid4(),
            property_id=pid,
            s3_key="photos/x.jpg",
            filename="x.jpg",
            content_type="image/jpeg",
            size_bytes=1024,
            display_order=0,
            created_at=now,
            updated_at=now,
        )
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
    prop = _complete_property()
    await repo.save(prop)
    version_before = prop.aggregate_version

    use_case = PublishProperty(property_repo=repo, domain_event_publisher=publisher)
    refreshed = await use_case.execute(property_id=prop.id, organization_id=ORG_ID)

    # Status flipped + version bumped
    assert refreshed.status == PropertyStatus.ACTIVE
    assert refreshed.aggregate_version == version_before + 1

    # Persisted in the repo too
    stored = await repo.get_by_id(prop.id)
    assert stored.status == PropertyStatus.ACTIVE
    assert stored.aggregate_version == version_before + 1

    # One event, correct type, payload matches build_property_snapshot(refreshed)
    assert len(publisher.published) == 1
    event = publisher.published[0]
    assert event.event_type == PROPERTY_PUBLISHED_V1
    assert event.data == build_property_snapshot(refreshed)
    assert event.data["status"] == "active"
    assert event.data["aggregate_version"] == version_before + 1


async def test_happy_path_from_withdrawn(repo, publisher):
    prop = _complete_property(status=PropertyStatus.WITHDRAWN)
    await repo.save(prop)

    use_case = PublishProperty(property_repo=repo, domain_event_publisher=publisher)
    refreshed = await use_case.execute(property_id=prop.id, organization_id=ORG_ID)

    assert refreshed.status == PropertyStatus.ACTIVE
    assert publisher.published[0].event_type == PROPERTY_PUBLISHED_V1


async def test_unknown_id_raises_not_found(repo, publisher):
    use_case = PublishProperty(property_repo=repo, domain_event_publisher=publisher)
    with pytest.raises(PropertyNotFoundError):
        await use_case.execute(property_id=uuid4(), organization_id=ORG_ID)
    assert publisher.published == []


async def test_wrong_org_collapses_to_not_found(repo, publisher):
    prop = _complete_property(organization_id=ORG_ID)
    await repo.save(prop)

    use_case = PublishProperty(property_repo=repo, domain_event_publisher=publisher)
    with pytest.raises(PropertyNotFoundError):
        await use_case.execute(property_id=prop.id, organization_id=OTHER_ORG_ID)
    assert publisher.published == []


async def test_domain_gap_bubbles_and_does_not_emit(repo, publisher):
    prop = _complete_property()
    prop.images = []
    await repo.save(prop)

    use_case = PublishProperty(property_repo=repo, domain_event_publisher=publisher)
    with pytest.raises(PropertyNotPublishableError) as exc:
        await use_case.execute(property_id=prop.id, organization_id=ORG_ID)
    assert "missing_image" in exc.value.reasons

    # No state change, no event
    stored = await repo.get_by_id(prop.id)
    assert stored.status == PropertyStatus.DRAFT
    assert publisher.published == []


async def test_republish_of_active_raises_with_status_reason(repo, publisher):
    prop = _complete_property(status=PropertyStatus.ACTIVE)
    await repo.save(prop)

    use_case = PublishProperty(property_repo=repo, domain_event_publisher=publisher)
    with pytest.raises(PropertyNotPublishableError) as exc:
        await use_case.execute(property_id=prop.id, organization_id=ORG_ID)
    assert exc.value.reasons == ["cannot_publish_from_status:active"]
    assert publisher.published == []


async def test_publish_failure_is_swallowed(repo):
    """Matches CreateProperty / UpdatePropertyOwnerContact: persistence has
    already committed by the time we publish, so a broken publisher must
    not fail the whole use case."""
    prop = _complete_property()
    await repo.save(prop)

    class BrokenPublisher:
        async def publish(self, _event):
            raise RuntimeError("SNS is down")

    use_case = PublishProperty(property_repo=repo, domain_event_publisher=BrokenPublisher())
    refreshed = await use_case.execute(property_id=prop.id, organization_id=ORG_ID)

    assert refreshed.status == PropertyStatus.ACTIVE
    # The status + version change still landed despite the broken publisher.
    stored = await repo.get_by_id(prop.id)
    assert stored.status == PropertyStatus.ACTIVE


async def test_no_publisher_wired_is_fine(repo):
    """Bootstrap may construct PublishProperty without a publisher — the
    use case should still succeed, same as CreateProperty does."""
    prop = _complete_property()
    await repo.save(prop)

    use_case = PublishProperty(property_repo=repo, domain_event_publisher=None)
    refreshed = await use_case.execute(property_id=prop.id, organization_id=ORG_ID)

    assert refreshed.status == PropertyStatus.ACTIVE
