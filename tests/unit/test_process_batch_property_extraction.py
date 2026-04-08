import pytest
from uuid import UUID, uuid4

from properties.adapters.inmemory.inmemory_document_classifier import (
    InMemoryDocumentClassifier,
)
from properties.adapters.inmemory.inmemory_document_content_repo import (
    InMemoryDocumentContentRepository,
)
from properties.adapters.inmemory.inmemory_document_extractor import (
    InMemoryDocumentExtractor,
)
from properties.adapters.inmemory.inmemory_document_parser import InMemoryDocumentParser
from properties.adapters.inmemory.inmemory_document_storage import InMemoryDocumentStorage
from properties.adapters.inmemory.inmemory_extraction_job_repo import (
    InMemoryExtractionJobRepository,
)
from properties.adapters.inmemory.inmemory_property_extractor import (
    InMemoryPropertyExtractor,
)
from properties.adapters.inmemory.inmemory_property_repo import InMemoryPropertyRepository
from properties.application.ports.document_classifier import (
    ClassifiedDocument,
    DocumentClassifier,
)
from properties.application.ports.document_data_extractor import DocumentDataExtractor
from properties.application.ports.property_extractor import (
    GeoLocationResult,
    PropertyExtractorService,
)
from properties.application.use_cases.process_batch_property_extraction import (
    ProcessBatchPropertyExtraction,
)
from properties.domain.exceptions import ExtractionJobNotFoundError
from properties.domain.models.document_content import DocumentContent
from properties.domain.models.extraction_job import (
    ExtractionJob,
    ExtractionJobStatus,
)

TEST_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
TEST_ORGANIZATION_ID = UUID("00000000-0000-0000-0000-000000000010")


def _make_pending_job(job_id: UUID | None = None, num_docs: int = 3) -> ExtractionJob:
    jid = job_id or uuid4()
    return ExtractionJob(
        id=jid,
        user_id=TEST_USER_ID,
        organization_id=TEST_ORGANIZATION_ID,
        status=ExtractionJobStatus.PENDING,
        document_keys=[f"extractions/{jid}/{i}.pdf" for i in range(num_docs)],
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
def classifier():
    return InMemoryDocumentClassifier()


@pytest.fixture
def property_extractor():
    return InMemoryPropertyExtractor()


@pytest.fixture
def document_extractor():
    return InMemoryDocumentExtractor()


@pytest.fixture
def prop_repo():
    return InMemoryPropertyRepository()


@pytest.fixture
def document_parser():
    return InMemoryDocumentParser()


@pytest.fixture
def document_content_repo():
    return InMemoryDocumentContentRepository()


@pytest.fixture
def use_case(
    job_repo,
    storage,
    document_parser,
    classifier,
    property_extractor,
    document_extractor,
    prop_repo,
    document_content_repo,
):
    return ProcessBatchPropertyExtraction(
        extraction_job_repo=job_repo,
        document_storage=storage,
        document_parser=document_parser,
        document_classifier=classifier,
        property_extractor=property_extractor,
        document_data_extractor=document_extractor,
        property_repo=prop_repo,
        document_content_repo=document_content_repo,
    )


class TestProcessBatchPropertyExtraction:
    async def test_happy_path_property_doc_plus_id_docs(
        self, use_case, job_repo, storage, prop_repo, document_content_repo
    ):
        """1 property doc + 2 ID docs → property + owners from ID docs."""
        job = _make_pending_job(num_docs=3)
        await job_repo.save(job)
        for key in job.document_keys:
            await storage.upload(key, b"fake-pdf", "application/pdf")

        result = await use_case.execute(job_id=str(job.id))

        assert result.status == ExtractionJobStatus.COMPLETED
        assert result.property_id is not None

        props = await prop_repo.list_by_organization(TEST_ORGANIZATION_ID)
        assert len(props) == 1
        assert props[0].address == "Rua das Flores 123, 4000-001 Porto"
        assert props[0].characteristics is not None
        # Owners come only from ID docs (InMemoryDocumentExtractor returns 1 per ID doc)
        assert len(props[0].owners) == 1

        # Geolocation populated
        assert props[0].latitude == pytest.approx(41.1579)
        assert props[0].longitude == pytest.approx(-8.6291)

        # Document contents were persisted
        contents = await document_content_repo.get_by_job_id(job.id)
        assert len(contents) == 3

    async def test_only_property_doc_has_zero_owners(
        self, job_repo, storage, prop_repo, document_parser, document_content_repo
    ):
        """Only property documents — no owners (owners only come from ID docs)."""

        class AllPropertyClassifier(DocumentClassifier):
            async def classify(self, document_texts):
                return [
                    ClassifiedDocument(
                        index=i, category="property_document", document_subtype="escritura"
                    )
                    for i in range(len(document_texts))
                ]

        uc = ProcessBatchPropertyExtraction(
            extraction_job_repo=job_repo,
            document_storage=storage,
            document_parser=document_parser,
            document_classifier=AllPropertyClassifier(),
            property_extractor=InMemoryPropertyExtractor(),
            document_data_extractor=InMemoryDocumentExtractor(),
            property_repo=prop_repo,
            document_content_repo=document_content_repo,
        )

        job = _make_pending_job(num_docs=1)
        await job_repo.save(job)
        for key in job.document_keys:
            await storage.upload(key, b"fake-pdf", "application/pdf")

        result = await uc.execute(job_id=str(job.id))

        assert result.status == ExtractionJobStatus.COMPLETED
        props = await prop_repo.list_by_organization(TEST_ORGANIZATION_ID)
        assert len(props) == 1
        assert len(props[0].owners) == 0

    async def test_only_id_docs_fails(
        self, job_repo, storage, prop_repo, document_parser, document_content_repo
    ):
        """Only ID documents — should fail (no property data)."""

        class AllIdClassifier(DocumentClassifier):
            async def classify(self, document_texts):
                return [
                    ClassifiedDocument(
                        index=i, category="personal_id", document_subtype="cartao_cidadao"
                    )
                    for i in range(len(document_texts))
                ]

        uc = ProcessBatchPropertyExtraction(
            extraction_job_repo=job_repo,
            document_storage=storage,
            document_parser=document_parser,
            document_classifier=AllIdClassifier(),
            property_extractor=InMemoryPropertyExtractor(),
            document_data_extractor=InMemoryDocumentExtractor(),
            property_repo=prop_repo,
            document_content_repo=document_content_repo,
        )

        job = _make_pending_job(num_docs=2)
        await job_repo.save(job)
        for key in job.document_keys:
            await storage.upload(key, b"fake-pdf", "application/pdf")

        result = await uc.execute(job_id=str(job.id))

        assert result.status == ExtractionJobStatus.FAILED
        assert "No property documents found" in result.error_message

    async def test_job_not_found(self, use_case):
        with pytest.raises(ExtractionJobNotFoundError):
            await use_case.execute(job_id=str(uuid4()))

    async def test_classification_error_marks_job_failed(
        self, job_repo, storage, prop_repo, document_parser, document_content_repo
    ):
        class FailingClassifier(DocumentClassifier):
            async def classify(self, document_texts):
                raise RuntimeError("Classification service unavailable")

        uc = ProcessBatchPropertyExtraction(
            extraction_job_repo=job_repo,
            document_storage=storage,
            document_parser=document_parser,
            document_classifier=FailingClassifier(),
            property_extractor=InMemoryPropertyExtractor(),
            document_data_extractor=InMemoryDocumentExtractor(),
            property_repo=prop_repo,
            document_content_repo=document_content_repo,
        )

        job = _make_pending_job(num_docs=1)
        await job_repo.save(job)
        for key in job.document_keys:
            await storage.upload(key, b"fake-pdf", "application/pdf")

        result = await uc.execute(job_id=str(job.id))

        assert result.status == ExtractionJobStatus.FAILED
        assert "Classification service unavailable" in result.error_message

    async def test_extraction_error_marks_job_failed(
        self, job_repo, storage, prop_repo, document_parser, document_content_repo
    ):
        class FailingExtractor(PropertyExtractorService):
            async def extract(self, document_texts):
                raise RuntimeError("AI service unavailable")

            async def extract_geolocation(self, address):
                return GeoLocationResult()

        uc = ProcessBatchPropertyExtraction(
            extraction_job_repo=job_repo,
            document_storage=storage,
            document_parser=document_parser,
            document_classifier=InMemoryDocumentClassifier(),
            property_extractor=FailingExtractor(),
            document_data_extractor=InMemoryDocumentExtractor(),
            property_repo=prop_repo,
            document_content_repo=document_content_repo,
        )

        job = _make_pending_job(num_docs=1)
        await job_repo.save(job)
        for key in job.document_keys:
            await storage.upload(key, b"fake-pdf", "application/pdf")

        result = await uc.execute(job_id=str(job.id))

        assert result.status == ExtractionJobStatus.FAILED
        assert "AI service unavailable" in result.error_message

    async def test_owner_dedup_by_nif_from_id_docs(
        self, job_repo, storage, prop_repo, document_parser, document_content_repo
    ):
        """When same NIF appears in multiple ID docs, last one wins."""

        class IdExtractorDuplicate(DocumentDataExtractor):
            def __init__(self):
                self._call_count = 0

            async def extract_property_owner_data(self, parsed_text, document_subtype):
                self._call_count += 1
                if self._call_count == 1:
                    return {
                        "full_name": "Name From First ID",
                        "civil_status": "single",
                        "address": "Rua Test 1",
                        "nif": "987654321",
                        "document_type": "cartao_cidadao",
                        "document_id": "FIRST-ID",
                        "issued_by": "First Authority",
                        "date_of_birth": "1990-01-01",
                    }
                return {
                    "full_name": "Name From Second ID",
                    "civil_status": "single",
                    "address": "Rua Test 1",
                    "nif": "987654321",
                    "document_type": "cartao_cidadao",
                    "document_id": "SECOND-ID",
                    "issued_by": "Second Authority",
                    "date_of_birth": "1990-01-01",
                }

        # Classifier: doc 0 = property, docs 1+2 = personal_id
        class MixedClassifier(DocumentClassifier):
            async def classify(self, document_texts):
                results = [
                    ClassifiedDocument(
                        index=0, category="property_document", document_subtype="escritura"
                    ),
                ]
                for i in range(1, len(document_texts)):
                    results.append(
                        ClassifiedDocument(
                            index=i, category="personal_id", document_subtype="cartao_cidadao"
                        )
                    )
                return results

        uc = ProcessBatchPropertyExtraction(
            extraction_job_repo=job_repo,
            document_storage=storage,
            document_parser=document_parser,
            document_classifier=MixedClassifier(),
            property_extractor=InMemoryPropertyExtractor(),
            document_data_extractor=IdExtractorDuplicate(),
            property_repo=prop_repo,
            document_content_repo=document_content_repo,
        )

        job = _make_pending_job(num_docs=3)
        await job_repo.save(job)
        for key in job.document_keys:
            await storage.upload(key, b"fake-pdf", "application/pdf")

        result = await uc.execute(job_id=str(job.id))

        assert result.status == ExtractionJobStatus.COMPLETED
        props = await prop_repo.list_by_organization(TEST_ORGANIZATION_ID)
        assert len(props[0].owners) == 1
        # Second ID doc wins (last write)
        assert props[0].owners[0].full_name == "Name From Second ID"
        assert props[0].owners[0].document_id == "SECOND-ID"

    async def test_geolocation_failure_does_not_fail_job(
        self, job_repo, storage, prop_repo, document_parser, document_content_repo
    ):
        class GeoFailExtractor(InMemoryPropertyExtractor):
            async def extract_geolocation(self, address):
                raise RuntimeError("Geolocation unavailable")

        uc = ProcessBatchPropertyExtraction(
            extraction_job_repo=job_repo,
            document_storage=storage,
            document_parser=document_parser,
            document_classifier=InMemoryDocumentClassifier(),
            property_extractor=GeoFailExtractor(),
            document_data_extractor=InMemoryDocumentExtractor(),
            property_repo=prop_repo,
            document_content_repo=document_content_repo,
        )

        job = _make_pending_job(num_docs=3)
        await job_repo.save(job)
        for key in job.document_keys:
            await storage.upload(key, b"fake-pdf", "application/pdf")

        result = await uc.execute(job_id=str(job.id))

        assert result.status == ExtractionJobStatus.COMPLETED
        props = await prop_repo.list_by_organization(TEST_ORGANIZATION_ID)
        assert props[0].latitude is None
        assert props[0].longitude is None

    async def test_retry_uses_cached_parsed_text(
        self, use_case, job_repo, storage, document_parser, document_content_repo, prop_repo
    ):
        """On retry, cached parsed text is used — no S3 download or Reducto parse."""
        job = _make_pending_job(num_docs=3)
        await job_repo.save(job)

        # Pre-populate document_contents as if first attempt parsed successfully
        for i, key in enumerate(job.document_keys):
            content = DocumentContent(
                id=uuid4(),
                extraction_job_id=job.id,
                document_index=i,
                document_key=key,
                parsed_text=f"Cached parsed text for doc {i}",
            )
            await document_content_repo.save(content)

        # Track calls to parser and storage
        parse_calls = []
        original_parse_batch = document_parser.parse_batch

        async def spy_parse_batch(documents):
            parse_calls.append(documents)
            return await original_parse_batch(documents)

        document_parser.parse_batch = spy_parse_batch

        download_calls = []
        original_download = storage.download

        async def spy_download(key):
            download_calls.append(key)
            return await original_download(key)

        storage.download = spy_download

        result = await use_case.execute(job_id=str(job.id))

        assert result.status == ExtractionJobStatus.COMPLETED
        assert result.property_id is not None
        assert len(parse_calls) == 0, "parse_batch should not be called on retry"
        assert len(download_calls) == 0, "download should not be called on retry"

        # Property was still created
        props = await prop_repo.list_by_organization(TEST_ORGANIZATION_ID)
        assert len(props) == 1

    async def test_completed_job_is_skipped_idempotently(
        self, use_case, job_repo, storage, prop_repo
    ):
        """Re-running a completed job is a no-op — no second Property is created."""
        job = _make_pending_job(num_docs=3)
        await job_repo.save(job)
        for key in job.document_keys:
            await storage.upload(key, b"fake-pdf", "application/pdf")

        first = await use_case.execute(job_id=str(job.id))
        assert first.status == ExtractionJobStatus.COMPLETED
        first_property_id = first.property_id

        # Second run on the same already-completed job
        result = await use_case.execute(job_id=str(job.id))

        assert result.status == ExtractionJobStatus.COMPLETED
        assert result.property_id == first_property_id

        # Only ONE property exists
        props = await prop_repo.list_by_organization(TEST_ORGANIZATION_ID)
        assert len(props) == 1
