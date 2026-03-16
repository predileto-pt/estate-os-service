from datetime import datetime
from uuid import uuid4

from property_management.domain.models.extraction_job import (
    ExtractionJob,
    ExtractionJobStatus,
)


def _make_job(**overrides) -> ExtractionJob:
    defaults = {
        "id": uuid4(),
        "user_id": uuid4(),
        "status": ExtractionJobStatus.PENDING,
        "document_keys": ["extractions/abc/0.pdf"],
    }
    defaults.update(overrides)
    return ExtractionJob(**defaults)


class TestExtractionJobStateTransitions:
    def test_mark_processing(self):
        job = _make_job()
        assert job.status == ExtractionJobStatus.PENDING

        job.mark_processing()
        assert job.status == ExtractionJobStatus.PROCESSING

    def test_mark_completed(self):
        job = _make_job()
        job.mark_processing()

        property_id = uuid4()
        job.mark_completed(property_id)

        assert job.status == ExtractionJobStatus.COMPLETED
        assert job.property_id == property_id

    def test_mark_failed(self):
        job = _make_job()
        job.mark_processing()

        job.mark_failed("OCR service unavailable")

        assert job.status == ExtractionJobStatus.FAILED
        assert job.error_message == "OCR service unavailable"

    def test_updated_at_changes_on_transition(self):
        job = _make_job()
        original = job.updated_at

        job.mark_processing()
        assert job.updated_at >= original

    def test_default_values(self):
        job = _make_job()
        assert job.property_id is None
        assert job.error_message is None
        assert isinstance(job.created_at, datetime)
        assert isinstance(job.updated_at, datetime)
