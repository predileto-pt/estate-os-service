import pytest
from uuid import UUID, uuid4

from property_management.adapters.inmemory.inmemory_document_storage import InMemoryDocumentStorage
from property_management.adapters.inmemory.inmemory_extraction_job_repo import (
    InMemoryExtractionJobRepository,
)
from property_management.adapters.inmemory.inmemory_property_extractor import (
    InMemoryPropertyExtractor,
)
from property_management.adapters.inmemory.inmemory_property_repo import InMemoryPropertyRepository
from property_management.application.ports.property_extractor import (
    PropertyExtractorService,
)
from property_management.application.use_cases.process_property_extraction import (
    ProcessPropertyExtraction,
)
from property_management.domain.exceptions import ExtractionJobNotFoundError
from property_management.domain.models.extraction_job import (
    ExtractionJob,
    ExtractionJobStatus,
)

TEST_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


def _make_pending_job(job_id: UUID | None = None) -> ExtractionJob:
    return ExtractionJob(
        id=job_id or uuid4(),
        user_id=TEST_USER_ID,
        status=ExtractionJobStatus.PENDING,
        document_keys=["extractions/test/0.pdf"],
        listing_type="sale",
        typology="apartment",
    )


@pytest.fixture
def storage():
    return InMemoryDocumentStorage()


@pytest.fixture
def job_repo():
    return InMemoryExtractionJobRepository()


@pytest.fixture
def extractor():
    return InMemoryPropertyExtractor()


@pytest.fixture
def prop_repo():
    return InMemoryPropertyRepository()


@pytest.fixture
def use_case(job_repo, storage, extractor, prop_repo):
    return ProcessPropertyExtraction(
        extraction_job_repo=job_repo,
        document_storage=storage,
        property_extractor=extractor,
        property_repo=prop_repo,
    )


class TestProcessPropertyExtraction:
    async def test_happy_path(self, use_case, job_repo, storage, prop_repo):
        job = _make_pending_job()
        await job_repo.save(job)
        await storage.upload("extractions/test/0.pdf", b"fake-pdf", "application/pdf")

        result = await use_case.execute(job_id=str(job.id))

        assert result.status == ExtractionJobStatus.COMPLETED
        assert result.property_id is not None

        # Property was created
        props = await prop_repo.list_by_user(TEST_USER_ID)
        assert len(props) == 1
        assert props[0].address == "Rua das Flores 123, 4000-001 Porto"
        assert props[0].characteristics is not None
        assert props[0].characteristics.area_in_m2 == 85.0
        assert len(props[0].owners) == 1

    async def test_job_not_found(self, use_case):
        with pytest.raises(ExtractionJobNotFoundError):
            await use_case.execute(job_id=str(uuid4()))

    async def test_failure_marks_job_failed(self, use_case, job_repo, storage):
        job = _make_pending_job()
        await job_repo.save(job)
        # Don't upload the file — download will fail

        result = await use_case.execute(job_id=str(job.id))

        assert result.status == ExtractionJobStatus.FAILED
        assert result.error_message is not None

    async def test_extractor_failure_marks_job_failed(self, job_repo, storage, prop_repo):
        class FailingExtractor(PropertyExtractorService):
            async def extract(self, documents):
                raise RuntimeError("AI service unavailable")

        uc = ProcessPropertyExtraction(
            extraction_job_repo=job_repo,
            document_storage=storage,
            property_extractor=FailingExtractor(),
            property_repo=prop_repo,
        )

        job = _make_pending_job()
        await job_repo.save(job)
        await storage.upload("extractions/test/0.pdf", b"fake-pdf", "application/pdf")

        result = await uc.execute(job_id=str(job.id))

        assert result.status == ExtractionJobStatus.FAILED
        assert "AI service unavailable" in result.error_message
