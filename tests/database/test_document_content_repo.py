from datetime import datetime, timezone
from uuid import uuid4

from customer_management.domain.models.organization import Organization
from property_management.domain.models.document_content import DocumentContent
from property_management.domain.models.extraction_job import ExtractionJob, ExtractionJobStatus


def _make_organization(**overrides) -> Organization:
    now = datetime.now(timezone.utc)
    defaults = {
        "id": uuid4(),
        "created_by": uuid4(),
        "name": "Test Organization",
        "nif": "123456789",
        "address": "Rua do Teste 1, Lisboa",
        "created_at": now,
        "updated_at": now,
    }
    return Organization(**(defaults | overrides))


def _make_extraction_job(organization_id=None, **overrides) -> ExtractionJob:
    now = datetime.now(timezone.utc)
    defaults = {
        "id": uuid4(),
        "user_id": uuid4(),
        "organization_id": organization_id or uuid4(),
        "status": ExtractionJobStatus.PENDING,
        "document_keys": ["docs/file1.pdf"],
        "created_at": now,
        "updated_at": now,
    }
    return ExtractionJob(**(defaults | overrides))


def _make_document_content(extraction_job_id, **overrides) -> DocumentContent:
    defaults = {
        "id": uuid4(),
        "extraction_job_id": extraction_job_id,
        "document_index": 0,
        "document_key": "docs/file1.pdf",
        "parsed_text": "This is parsed document text.",
        "category": None,
        "document_subtype": None,
        "created_at": None,
    }
    return DocumentContent(**(defaults | overrides))


async def test_save_and_get_by_job_id(
    organization_repo, extraction_job_repo, document_content_repo
):
    org = await organization_repo.save(_make_organization())
    job = _make_extraction_job(organization_id=org.id)
    await extraction_job_repo.save(job)

    content = _make_document_content(job.id)
    saved = await document_content_repo.save(content)
    assert saved.id == content.id
    assert saved.parsed_text == "This is parsed document text."

    results = await document_content_repo.get_by_job_id(job.id)
    assert len(results) == 1
    assert results[0].document_key == "docs/file1.pdf"


async def test_save_batch(organization_repo, extraction_job_repo, document_content_repo):
    org = await organization_repo.save(_make_organization())
    job = _make_extraction_job(organization_id=org.id)
    await extraction_job_repo.save(job)

    contents = [
        _make_document_content(job.id, document_index=0, document_key="docs/file1.pdf"),
        _make_document_content(job.id, document_index=1, document_key="docs/file2.pdf"),
        _make_document_content(job.id, document_index=2, document_key="docs/file3.pdf"),
    ]
    saved = await document_content_repo.save_batch(contents)
    assert len(saved) == 3

    results = await document_content_repo.get_by_job_id(job.id)
    assert len(results) == 3
    # Verify ordered by document_index
    assert [r.document_index for r in results] == [0, 1, 2]


async def test_update_classification(organization_repo, extraction_job_repo, document_content_repo):
    org = await organization_repo.save(_make_organization())
    job = _make_extraction_job(organization_id=org.id)
    await extraction_job_repo.save(job)

    content = _make_document_content(job.id)
    saved = await document_content_repo.save(content)

    await document_content_repo.update_classification(
        saved.id, category="property_document", document_subtype="escritura"
    )

    results = await document_content_repo.get_by_job_id(job.id)
    assert results[0].category == "property_document"
    assert results[0].document_subtype == "escritura"


async def test_ordering_by_document_index(
    organization_repo, extraction_job_repo, document_content_repo
):
    org = await organization_repo.save(_make_organization())
    job = _make_extraction_job(organization_id=org.id)
    await extraction_job_repo.save(job)

    # Save in reverse order
    for i in [2, 0, 1]:
        await document_content_repo.save(
            _make_document_content(job.id, document_index=i, document_key=f"docs/file{i}.pdf")
        )

    results = await document_content_repo.get_by_job_id(job.id)
    assert [r.document_index for r in results] == [0, 1, 2]
