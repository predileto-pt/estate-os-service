"""Tests for the JobTracker integration on SubmitPropertyExtraction +
ProcessPropertyExtraction (ADR-012)."""

from uuid import UUID

from properties.adapters.inmemory.inmemory_document_parser import InMemoryDocumentParser
from properties.adapters.inmemory.inmemory_document_storage import InMemoryDocumentStorage
from properties.adapters.inmemory.inmemory_extraction_job_repo import (
    InMemoryExtractionJobRepository,
)
from properties.adapters.inmemory.inmemory_property_extractor import (
    InMemoryPropertyExtractor,
)
from properties.adapters.inmemory.inmemory_property_repo import InMemoryPropertyRepository
from properties.application.use_cases.process_property_extraction import (
    ProcessPropertyExtraction,
)
from properties.application.use_cases.submit_property_extraction import (
    SubmitPropertyExtraction,
)
from properties.domain.models.extraction_job import ExtractionJobStatus
from shared.events.adapters.inmemory_event_bus import InMemoryCommandPublisher
from shared.jobs.adapters.persistence.inmemory_job_repository import (
    InMemoryJobRepository,
)
from shared.jobs.adapters.tracking.default_job_tracker import DefaultJobTracker
from shared.jobs.domain.job import JobEntityType, JobKind, JobStatus

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
TEST_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000010"
TEST_QUEUE_URL = "test-extraction-queue"


async def _build_submit():
    storage = InMemoryDocumentStorage()
    job_repo = InMemoryExtractionJobRepository()
    publisher = InMemoryCommandPublisher()
    job_tracker_repo = InMemoryJobRepository()
    tracker = DefaultJobTracker(job_tracker_repo)
    use_case = SubmitPropertyExtraction(
        document_storage=storage,
        extraction_job_repo=job_repo,
        command_publisher=publisher,
        extraction_queue_url=TEST_QUEUE_URL,
        job_tracker=tracker,
    )
    return storage, job_repo, publisher, job_tracker_repo, use_case


async def test_submit_starts_job_and_bakes_tracked_id_into_extraction_row():
    storage, job_repo, publisher, tracker_repo, submit = await _build_submit()
    job_id = "11111111-1111-1111-1111-111111111111"
    keys = [f"extractions/{job_id}/0.pdf"]
    await storage.upload(keys[0], b"fake-pdf", "application/pdf")

    job = await submit.execute(
        job_id=job_id,
        user_id=TEST_USER_ID,
        organization_id=TEST_ORGANIZATION_ID,
        document_keys=keys,
        listing_type="sale",
        typology="apartment",
    )

    # Extraction row carries the tracked_job_id.
    assert job.tracked_job_id is not None
    persisted = await job_repo.get_by_id(UUID(job_id))
    assert persisted.tracked_job_id == job.tracked_job_id

    # Unified row exists, kind PROPERTY_DOCUMENT_EXTRACTION, entity_id ==
    # the extraction-job id (placeholder until completion repoints it).
    tracked = await tracker_repo.get_by_id(job.tracked_job_id)
    assert tracked.kind == JobKind.PROPERTY_DOCUMENT_EXTRACTION
    assert tracked.entity_type == JobEntityType.PROPERTY
    assert tracked.entity_id == UUID(job_id)
    assert tracked.status == JobStatus.PROCESSING
    assert "documento" in tracked.title.lower()


async def test_process_success_repoints_entity_id_and_completes():
    storage, job_repo, publisher, tracker_repo, submit = await _build_submit()
    job_id = "11111111-1111-1111-1111-111111111111"
    keys = [f"extractions/{job_id}/0.pdf"]
    await storage.upload(keys[0], b"fake-pdf", "application/pdf")
    submitted = await submit.execute(
        job_id=job_id,
        user_id=TEST_USER_ID,
        organization_id=TEST_ORGANIZATION_ID,
        document_keys=keys,
        listing_type="sale",
        typology="apartment",
    )
    tracked_id = submitted.tracked_job_id
    assert tracked_id is not None

    property_repo = InMemoryPropertyRepository()
    process = ProcessPropertyExtraction(
        extraction_job_repo=job_repo,
        document_storage=storage,
        document_parser=InMemoryDocumentParser(),
        property_extractor=InMemoryPropertyExtractor(),
        property_repo=property_repo,
        domain_event_publisher=None,
        job_tracker=DefaultJobTracker(tracker_repo),  # share the same repo
    )

    result_job = await process.execute(job_id=job_id)
    assert result_job.status == ExtractionJobStatus.COMPLETED
    assert result_job.property_id is not None

    tracked = await tracker_repo.get_by_id(tracked_id)
    assert tracked.status == JobStatus.COMPLETED
    # entity_id was repointed from extraction_job.id → property.id.
    assert tracked.entity_id == result_job.property_id
    assert tracked.result_summary["created_property_id"] == str(result_job.property_id)


async def test_process_failure_marks_job_failed_extraction_failed():
    """When ProcessPropertyExtraction raises during the work, the unified
    row transitions to FAILED with `extraction_failed` error_code."""

    class FailingPropertyExtractor:
        async def extract(self, parsed_texts):
            raise RuntimeError("extractor down")

        async def extract_geolocation(self, address):
            return None

    storage = InMemoryDocumentStorage()
    job_repo = InMemoryExtractionJobRepository()
    publisher = InMemoryCommandPublisher()
    tracker_repo = InMemoryJobRepository()
    tracker = DefaultJobTracker(tracker_repo)
    submit = SubmitPropertyExtraction(
        document_storage=storage,
        extraction_job_repo=job_repo,
        command_publisher=publisher,
        extraction_queue_url=TEST_QUEUE_URL,
        job_tracker=tracker,
    )
    job_id = "22222222-2222-2222-2222-222222222222"
    keys = [f"extractions/{job_id}/0.pdf"]
    await storage.upload(keys[0], b"fake-pdf", "application/pdf")
    submitted = await submit.execute(
        job_id=job_id,
        user_id=TEST_USER_ID,
        organization_id=TEST_ORGANIZATION_ID,
        document_keys=keys,
        listing_type="sale",
        typology="apartment",
    )

    property_repo = InMemoryPropertyRepository()
    process = ProcessPropertyExtraction(
        extraction_job_repo=job_repo,
        document_storage=storage,
        document_parser=InMemoryDocumentParser(),
        property_extractor=FailingPropertyExtractor(),
        property_repo=property_repo,
        domain_event_publisher=None,
        job_tracker=tracker,
    )

    result_job = await process.execute(job_id=job_id)
    assert result_job.status == ExtractionJobStatus.FAILED

    tracked = await tracker_repo.get_by_id(submitted.tracked_job_id)
    assert tracked.status == JobStatus.FAILED
    assert tracked.error_code == "extraction_failed"
