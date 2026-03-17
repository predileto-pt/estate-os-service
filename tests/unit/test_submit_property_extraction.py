import pytest

from property_management.adapters.inmemory.inmemory_document_storage import InMemoryDocumentStorage
from property_management.adapters.inmemory.inmemory_event_bus import InMemoryEventBus
from property_management.adapters.inmemory.inmemory_extraction_job_repo import (
    InMemoryExtractionJobRepository,
)
from property_management.application.use_cases.submit_property_extraction import (
    SubmitPropertyExtraction,
)
from property_management.domain.models.extraction_job import ExtractionJobStatus

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
TEST_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000010"


@pytest.fixture
def storage():
    return InMemoryDocumentStorage()


@pytest.fixture
def job_repo():
    return InMemoryExtractionJobRepository()


@pytest.fixture
def bus():
    return InMemoryEventBus()


@pytest.fixture
def use_case(storage, job_repo, bus):
    return SubmitPropertyExtraction(
        document_storage=storage,
        extraction_job_repo=job_repo,
        event_bus=bus,
    )


class TestSubmitPropertyExtraction:
    async def test_happy_path(self, use_case, storage, job_repo, bus):
        job_id = "11111111-1111-1111-1111-111111111111"
        keys = [f"extractions/{job_id}/0.pdf", f"extractions/{job_id}/1.pdf"]

        # Pre-populate S3
        for key in keys:
            await storage.upload(key, b"fake-pdf", "application/pdf")

        job = await use_case.execute(
            job_id=job_id,
            user_id=TEST_USER_ID,
            organization_id=TEST_ORGANIZATION_ID,
            document_keys=keys,
            listing_type="sale",
            typology="apartment",
        )

        assert job.status == ExtractionJobStatus.PENDING
        assert job.document_keys == keys
        assert job.listing_type == "sale"
        assert job.typology == "apartment"
        assert len(bus.events) == 1
        assert bus.events[0]["event_type"] == "PROPERTY_EXTRACTION_REQUESTED"
        assert bus.events[0]["data"]["job_id"] == job_id

    async def test_invalid_s3_key_prefix(self, use_case, storage):
        job_id = "11111111-1111-1111-1111-111111111111"
        key = "wrong-prefix/file.pdf"
        await storage.upload(key, b"fake-pdf", "application/pdf")

        with pytest.raises(ValueError, match="Invalid S3 key"):
            await use_case.execute(
                job_id=job_id,
                user_id=TEST_USER_ID,
                organization_id=TEST_ORGANIZATION_ID,
                document_keys=[key],
                listing_type="sale",
                typology="house",
            )

    async def test_document_not_found_in_s3(self, use_case):
        job_id = "11111111-1111-1111-1111-111111111111"
        key = f"extractions/{job_id}/0.pdf"

        with pytest.raises(FileNotFoundError, match="Document not found"):
            await use_case.execute(
                job_id=job_id,
                user_id=TEST_USER_ID,
                organization_id=TEST_ORGANIZATION_ID,
                document_keys=[key],
                listing_type="sale",
                typology="house",
            )

    async def test_job_persisted(self, use_case, storage, job_repo):
        job_id = "11111111-1111-1111-1111-111111111111"
        key = f"extractions/{job_id}/0.pdf"
        await storage.upload(key, b"fake-pdf", "application/pdf")

        await use_case.execute(
            job_id=job_id,
            user_id=TEST_USER_ID,
            organization_id=TEST_ORGANIZATION_ID,
            document_keys=[key],
            listing_type="sale",
            typology="house",
        )

        from uuid import UUID

        saved = await job_repo.get_by_id(UUID(job_id))
        assert saved is not None
        assert saved.status == ExtractionJobStatus.PENDING
        assert saved.listing_type == "sale"
        assert saved.typology == "house"
