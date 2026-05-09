"""Unit tests covering EnqueueEnrichProperty's JobTracker integration.

Asserts that calling the use case (a) starts a unified Job row,
(b) bakes `tracked_job_id` into the SQS payload, (c) returns the id.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from properties.adapters.inmemory.inmemory_property_repo import InMemoryPropertyRepository
from properties.application.use_cases.enqueue_enrich_property import EnqueueEnrichProperty
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
from shared.jobs.adapters.persistence.inmemory_job_repository import (
    InMemoryJobRepository,
)
from shared.jobs.adapters.tracking.default_job_tracker import DefaultJobTracker
from shared.jobs.domain.job import JobEntityType, JobKind, JobStatus


def _make_property(*, organization_id, latitude=38.768, longitude=-9.108) -> Property:
    now = datetime.now(timezone.utc)
    return Property(
        id=uuid4(),
        organization_id=organization_id,
        address="Avenida da Liberdade 12",
        listing_type=ListingType.SALE,
        typology=Typology.APARTMENT,
        status=PropertyStatus.DRAFT,
        description=None,
        characteristics=None,
        latitude=latitude,
        longitude=longitude,
        created_at=now,
        updated_at=now,
    )


async def _setup():
    property_repo = InMemoryPropertyRepository()
    command_publisher = InMemoryCommandPublisher()
    job_repo = InMemoryJobRepository()
    job_tracker = DefaultJobTracker(job_repo)
    use_case = EnqueueEnrichProperty(
        property_repo=property_repo,
        command_publisher=command_publisher,
        enrichment_queue_url="test-queue",
        job_tracker=job_tracker,
    )
    return property_repo, command_publisher, job_repo, use_case


async def test_happy_path_starts_job_and_returns_tracked_id():
    property_repo, command_publisher, job_repo, use_case = await _setup()
    org_id = uuid4()
    user_id = uuid4()
    prop = _make_property(organization_id=org_id)
    await property_repo.save(prop)

    tracked_job_id = await use_case.execute(
        property_id=prop.id,
        organization_id=org_id,
        force=False,
        requested_by_user_id=user_id,
    )

    assert tracked_job_id is not None
    job = await job_repo.get_by_id(tracked_job_id)
    assert job is not None
    assert job.kind == JobKind.PROPERTY_ENRICHMENT
    assert job.entity_type == JobEntityType.PROPERTY
    assert job.entity_id == prop.id
    assert job.organization_id == org_id
    assert job.requested_by_user_id == user_id
    assert job.status == JobStatus.PROCESSING
    assert "Avenida da Liberdade" in job.title


async def test_payload_includes_tracked_job_id():
    property_repo, command_publisher, _, use_case = await _setup()
    org_id = uuid4()
    prop = _make_property(organization_id=org_id)
    await property_repo.save(prop)

    tracked_job_id = await use_case.execute(
        property_id=prop.id,
        organization_id=org_id,
        force=True,
        requested_by_user_id=uuid4(),
    )

    assert len(command_publisher.sent) == 1
    _, event = command_publisher.sent[0]
    assert event.data["tracked_job_id"] == str(tracked_job_id)
    assert event.data["force"] is True


async def test_property_not_found_doesnt_create_job():
    property_repo, command_publisher, job_repo, use_case = await _setup()
    with pytest.raises(PropertyNotFoundError):
        await use_case.execute(
            property_id=uuid4(),
            organization_id=uuid4(),
            force=False,
            requested_by_user_id=uuid4(),
        )
    assert len(job_repo._rows) == 0
    assert command_publisher.sent == []


async def test_missing_coordinates_doesnt_create_job():
    property_repo, command_publisher, job_repo, use_case = await _setup()
    org_id = uuid4()
    prop = _make_property(organization_id=org_id, latitude=None, longitude=None)
    await property_repo.save(prop)

    with pytest.raises(PropertyMissingCoordinatesError):
        await use_case.execute(
            property_id=prop.id,
            organization_id=org_id,
            force=False,
            requested_by_user_id=uuid4(),
        )

    assert len(job_repo._rows) == 0
    assert command_publisher.sent == []


async def test_works_without_job_tracker_returns_none():
    """Backward-compat: containers without a tracker still work; the route
    just gets None back and the response shape adapts."""
    property_repo = InMemoryPropertyRepository()
    command_publisher = InMemoryCommandPublisher()
    use_case = EnqueueEnrichProperty(
        property_repo=property_repo,
        command_publisher=command_publisher,
        enrichment_queue_url="test-queue",
        job_tracker=None,
    )
    org_id = uuid4()
    prop = _make_property(organization_id=org_id)
    await property_repo.save(prop)

    result = await use_case.execute(
        property_id=prop.id,
        organization_id=org_id,
        force=False,
        requested_by_user_id=uuid4(),
    )
    assert result is None
    assert command_publisher.sent[0][1].data["tracked_job_id"] is None
