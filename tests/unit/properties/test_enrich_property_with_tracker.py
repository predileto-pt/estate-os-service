"""Unit tests covering EnrichProperty's JobTracker integration.

Asserts that on success the tracked row transitions to COMPLETED with a
result_summary, and on every failure path the row transitions to FAILED
with the right `error_code` while the exception still propagates.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from properties.adapters.inmemory.inmemory_places_service import (
    InMemoryPlacesService,
)
from properties.adapters.inmemory.inmemory_property_poi_repo import (
    InMemoryPropertyPoiRepository,
)
from properties.adapters.inmemory.inmemory_property_repo import InMemoryPropertyRepository
from properties.application.use_cases.enrich_property import EnrichProperty
from properties.domain.exceptions import (
    PropertyMissingCoordinatesError,
    PropertyNotFoundError,
)
from properties.domain.models.nearby_place import NearbyPlace
from properties.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)
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


async def _setup(*, places_results: dict | None = None):
    property_repo = InMemoryPropertyRepository()
    poi_repo = InMemoryPropertyPoiRepository()
    places = InMemoryPlacesService(results=places_results)
    job_repo = InMemoryJobRepository()
    tracker = DefaultJobTracker(job_repo)
    use_case = EnrichProperty(
        property_repo=property_repo,
        property_poi_repo=poi_repo,
        places_service=places,
        job_tracker=tracker,
    )
    return property_repo, poi_repo, places, tracker, job_repo, use_case


async def _start_job(tracker, *, property_id, organization_id):
    return await tracker.start(
        organization_id=organization_id,
        requested_by_user_id=uuid4(),
        kind=JobKind.PROPERTY_ENRICHMENT,
        entity_type=JobEntityType.PROPERTY,
        entity_id=property_id,
        title="enrich",
    )


async def test_success_marks_job_completed_with_summary():
    property_repo, poi_repo, places, tracker, job_repo, use_case = await _setup(
        places_results={
            "supermarket": [
                NearbyPlace(
                    name="Pingo Doce",
                    distance_meters=120.0,
                    latitude=38.769,
                    longitude=-9.108,
                    place_id="abc",
                )
            ],
        }
    )
    org_id = uuid4()
    prop = _make_property(organization_id=org_id)
    await property_repo.save(prop)

    tracked_job_id = await _start_job(tracker, property_id=prop.id, organization_id=org_id)
    await use_case.execute(
        property_id=prop.id,
        force=False,
        requested_by_user_id=uuid4(),
        tracked_job_id=tracked_job_id,
    )

    job = await job_repo.get_by_id(tracked_job_id)
    assert job.status == JobStatus.COMPLETED
    assert job.result_summary["pois_discovered"] >= 1
    assert "categories_processed" in job.result_summary
    assert "had_failures" in job.result_summary


async def test_property_not_found_marks_job_failed_and_reraises():
    _, _, _, tracker, job_repo, use_case = await _setup()
    bogus_id = uuid4()
    tracked_job_id = await _start_job(tracker, property_id=bogus_id, organization_id=uuid4())

    with pytest.raises(PropertyNotFoundError):
        await use_case.execute(
            property_id=bogus_id,
            force=False,
            requested_by_user_id=uuid4(),
            tracked_job_id=tracked_job_id,
        )

    job = await job_repo.get_by_id(tracked_job_id)
    assert job.status == JobStatus.FAILED
    assert job.error_code == "property_not_found"


async def test_missing_coordinates_marks_job_failed_and_reraises():
    property_repo, _, _, tracker, job_repo, use_case = await _setup()
    org_id = uuid4()
    prop = _make_property(organization_id=org_id, latitude=None, longitude=None)
    await property_repo.save(prop)
    tracked_job_id = await _start_job(tracker, property_id=prop.id, organization_id=org_id)

    with pytest.raises(PropertyMissingCoordinatesError):
        await use_case.execute(
            property_id=prop.id,
            force=False,
            requested_by_user_id=uuid4(),
            tracked_job_id=tracked_job_id,
        )

    job = await job_repo.get_by_id(tracked_job_id)
    assert job.status == JobStatus.FAILED
    assert job.error_code == "property_missing_coordinates"


async def test_provider_outage_marks_job_failed_provider_unavailable():
    """All categories return 0 results AND at least one find_nearby raised
    → provider_unavailable error_code, exception re-raised so SQS retries."""

    class FailingPlacesService:
        async def find_nearby(self, *args, **kwargs):
            raise RuntimeError("places api down")

        async def get_place_details(self, place_id, *, include_reviews=True):
            return None

    property_repo = InMemoryPropertyRepository()
    poi_repo = InMemoryPropertyPoiRepository()
    job_repo = InMemoryJobRepository()
    tracker = DefaultJobTracker(job_repo)
    use_case = EnrichProperty(
        property_repo=property_repo,
        property_poi_repo=poi_repo,
        places_service=FailingPlacesService(),
        job_tracker=tracker,
    )

    org_id = uuid4()
    prop = _make_property(organization_id=org_id)
    await property_repo.save(prop)
    tracked_job_id = await _start_job(tracker, property_id=prop.id, organization_id=org_id)

    with pytest.raises(RuntimeError):
        await use_case.execute(
            property_id=prop.id,
            force=False,
            requested_by_user_id=uuid4(),
            tracked_job_id=tracked_job_id,
        )

    job = await job_repo.get_by_id(tracked_job_id)
    assert job.status == JobStatus.FAILED
    assert job.error_code == "provider_unavailable"


async def test_runs_without_tracker():
    """Backward-compat: enrich works when no tracker is wired (passing
    tracked_job_id=None)."""
    property_repo = InMemoryPropertyRepository()
    poi_repo = InMemoryPropertyPoiRepository()
    use_case = EnrichProperty(
        property_repo=property_repo,
        property_poi_repo=poi_repo,
        places_service=InMemoryPlacesService(),
        job_tracker=None,
    )
    org_id = uuid4()
    prop = _make_property(organization_id=org_id)
    await property_repo.save(prop)

    pois = await use_case.execute(
        property_id=prop.id,
        force=False,
        requested_by_user_id=uuid4(),
        tracked_job_id=None,
    )
    # No POIs match (places service returns empty by default), but no
    # provider-down because no failures either.
    assert isinstance(pois, list)
