"""Unit tests for `EnqueueEnrichProperty` — the HTTP-layer enqueue half."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from properties.adapters.inmemory.inmemory_property_repo import InMemoryPropertyRepository
from properties.application.use_cases.enqueue_enrich_property import (
    EnqueueEnrichProperty,
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
from shared.events.adapters.inmemory_event_bus import InMemoryCommandPublisher
from shared.events.types import ENRICH_PROPERTY_REQUESTED_V1

ORG_ID = UUID("00000000-0000-0000-0000-000000000010")
OTHER_ORG_ID = UUID("00000000-0000-0000-0000-000000000099")
USER_ID = UUID("00000000-0000-0000-0000-000000000001")
ENRICH_QUEUE_URL = "test-enrichment-queue"


def _property(
    *,
    organization_id: UUID = ORG_ID,
    latitude: float | None = 38.768,
    longitude: float | None = -9.108,
) -> Property:
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
        latitude=latitude,
        longitude=longitude,
    )


@pytest.fixture
def property_repo() -> InMemoryPropertyRepository:
    return InMemoryPropertyRepository()


@pytest.fixture
def publisher() -> InMemoryCommandPublisher:
    return InMemoryCommandPublisher()


async def test_happy_path_publishes_command(property_repo, publisher):
    prop = _property()
    await property_repo.save(prop)

    use_case = EnqueueEnrichProperty(
        property_repo=property_repo,
        command_publisher=publisher,
        enrichment_queue_url=ENRICH_QUEUE_URL,
    )
    await use_case.execute(
        property_id=prop.id,
        organization_id=ORG_ID,
        force=False,
        requested_by_user_id=USER_ID,
    )

    assert len(publisher.sent) == 1
    queue_url, event = publisher.sent[0]
    assert queue_url == ENRICH_QUEUE_URL
    assert event.event_type == ENRICH_PROPERTY_REQUESTED_V1
    assert event.data == {
        "property_id": str(prop.id),
        "organization_id": str(ORG_ID),
        "force": False,
        "requested_by_user_id": str(USER_ID),
        # Set when a JobTracker is wired (ADR-012); None when constructed
        # without one — this test runs without a tracker.
        "tracked_job_id": None,
    }


async def test_force_true_propagates_to_payload(property_repo, publisher):
    prop = _property()
    await property_repo.save(prop)

    use_case = EnqueueEnrichProperty(
        property_repo=property_repo,
        command_publisher=publisher,
        enrichment_queue_url=ENRICH_QUEUE_URL,
    )
    await use_case.execute(
        property_id=prop.id,
        organization_id=ORG_ID,
        force=True,
        requested_by_user_id=USER_ID,
    )

    assert publisher.sent[0][1].data["force"] is True


async def test_unknown_property_raises_not_found(property_repo, publisher):
    use_case = EnqueueEnrichProperty(
        property_repo=property_repo,
        command_publisher=publisher,
        enrichment_queue_url=ENRICH_QUEUE_URL,
    )
    with pytest.raises(PropertyNotFoundError):
        await use_case.execute(
            property_id=uuid4(),
            organization_id=ORG_ID,
            force=False,
            requested_by_user_id=USER_ID,
        )
    assert publisher.sent == []


async def test_cross_org_raises_not_found(property_repo, publisher):
    """Caller is a member of OTHER_ORG_ID but property belongs to ORG_ID
    → 404 (we don't leak property existence cross-org)."""
    prop = _property(organization_id=ORG_ID)
    await property_repo.save(prop)

    use_case = EnqueueEnrichProperty(
        property_repo=property_repo,
        command_publisher=publisher,
        enrichment_queue_url=ENRICH_QUEUE_URL,
    )
    with pytest.raises(PropertyNotFoundError):
        await use_case.execute(
            property_id=prop.id,
            organization_id=OTHER_ORG_ID,
            force=False,
            requested_by_user_id=USER_ID,
        )
    assert publisher.sent == []


async def test_missing_coordinates_raises(property_repo, publisher):
    prop = _property(latitude=None, longitude=None)
    await property_repo.save(prop)

    use_case = EnqueueEnrichProperty(
        property_repo=property_repo,
        command_publisher=publisher,
        enrichment_queue_url=ENRICH_QUEUE_URL,
    )
    with pytest.raises(PropertyMissingCoordinatesError):
        await use_case.execute(
            property_id=prop.id,
            organization_id=ORG_ID,
            force=False,
            requested_by_user_id=USER_ID,
        )
    assert publisher.sent == []
