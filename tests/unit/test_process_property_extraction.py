import pytest
from uuid import UUID, uuid4

from properties.adapters.inmemory.inmemory_document_parser import InMemoryDocumentParser
from properties.adapters.inmemory.inmemory_document_storage import InMemoryDocumentStorage
from properties.adapters.inmemory.inmemory_extraction_job_repo import (
    InMemoryExtractionJobRepository,
)
from properties.adapters.inmemory.inmemory_property_extractor import (
    InMemoryPropertyExtractor,
)
from properties.adapters.inmemory.inmemory_property_repo import InMemoryPropertyRepository
from properties.application.ports.property_extractor import (
    GeoLocationResult,
    PropertyExtractorService,
)
from properties.application.use_cases.process_property_extraction import (
    ProcessPropertyExtraction,
)
from properties.domain.exceptions import ExtractionJobNotFoundError
from properties.domain.models.extraction_job import (
    ExtractionJob,
    ExtractionJobStatus,
)

TEST_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
TEST_ORGANIZATION_ID = UUID("00000000-0000-0000-0000-000000000010")


def _make_pending_job(job_id: UUID | None = None) -> ExtractionJob:
    return ExtractionJob(
        id=job_id or uuid4(),
        user_id=TEST_USER_ID,
        organization_id=TEST_ORGANIZATION_ID,
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
def document_parser():
    return InMemoryDocumentParser()


@pytest.fixture
def use_case(job_repo, storage, document_parser, extractor, prop_repo):
    return ProcessPropertyExtraction(
        extraction_job_repo=job_repo,
        document_storage=storage,
        document_parser=document_parser,
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

        # Property was created with no owners
        props = await prop_repo.list_by_organization(TEST_ORGANIZATION_ID)
        assert len(props) == 1
        assert props[0].address == "Rua das Flores 123, 4000-001 Porto"
        assert props[0].characteristics is not None
        assert props[0].characteristics.area_in_m2 == 85.0
        assert len(props[0].owners) == 0

    async def test_geolocation_populated(self, use_case, job_repo, storage, prop_repo):
        job = _make_pending_job()
        await job_repo.save(job)
        await storage.upload("extractions/test/0.pdf", b"fake-pdf", "application/pdf")

        await use_case.execute(job_id=str(job.id))

        props = await prop_repo.list_by_organization(TEST_ORGANIZATION_ID)
        assert props[0].latitude == pytest.approx(41.1579)
        assert props[0].longitude == pytest.approx(-8.6291)

    async def test_geolocation_failure_does_not_fail_job(
        self, job_repo, storage, prop_repo, document_parser
    ):
        class GeoFailExtractor(InMemoryPropertyExtractor):
            async def extract_geolocation(self, address):
                raise RuntimeError("Geolocation unavailable")

        uc = ProcessPropertyExtraction(
            extraction_job_repo=job_repo,
            document_storage=storage,
            document_parser=document_parser,
            property_extractor=GeoFailExtractor(),
            property_repo=prop_repo,
        )

        job = _make_pending_job()
        await job_repo.save(job)
        await storage.upload("extractions/test/0.pdf", b"fake-pdf", "application/pdf")

        result = await uc.execute(job_id=str(job.id))

        assert result.status == ExtractionJobStatus.COMPLETED
        props = await prop_repo.list_by_organization(TEST_ORGANIZATION_ID)
        assert props[0].latitude is None
        assert props[0].longitude is None

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

    async def test_extractor_failure_marks_job_failed(
        self, job_repo, storage, prop_repo, document_parser
    ):
        class FailingExtractor(PropertyExtractorService):
            async def extract(self, document_texts):
                raise RuntimeError("AI service unavailable")

            async def extract_geolocation(self, address):
                return GeoLocationResult()

        uc = ProcessPropertyExtraction(
            extraction_job_repo=job_repo,
            document_storage=storage,
            document_parser=document_parser,
            property_extractor=FailingExtractor(),
            property_repo=prop_repo,
        )

        job = _make_pending_job()
        await job_repo.save(job)
        await storage.upload("extractions/test/0.pdf", b"fake-pdf", "application/pdf")

        result = await uc.execute(job_id=str(job.id))

        assert result.status == ExtractionJobStatus.FAILED
        assert "AI service unavailable" in result.error_message
