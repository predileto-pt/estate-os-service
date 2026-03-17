from datetime import datetime, timezone
from uuid import uuid4

from customer_management.domain.models.organization import Organization
from customer_management.domain.models.user import User
from customer_management.domain.models.value_objects import PhoneNumber
from property_management.domain.models.extraction_job import ExtractionJob, ExtractionJobStatus
from property_management.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)


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


def _make_user(organization_id, **overrides) -> User:
    now = datetime.now(timezone.utc)
    defaults = {
        "id": uuid4(),
        "supabase_user_id": str(uuid4()),
        "email": f"user-{uuid4().hex[:8]}@test.com",
        "name": "Test User",
        "phone": PhoneNumber(country_code="+351", number="912345678"),
        "organization_id": organization_id,
        "google_metadata": None,
        "created_at": now,
        "updated_at": now,
    }
    return User(**(defaults | overrides))


def _make_property(organization_id, **overrides) -> Property:
    now = datetime.now(timezone.utc)
    defaults = {
        "id": uuid4(),
        "organization_id": organization_id,
        "address": "Rua da Propriedade 1, Lisboa",
        "listing_type": ListingType.SALE,
        "typology": Typology.APARTMENT,
        "status": PropertyStatus.DRAFT,
        "description": "A test property",
        "created_at": now,
        "updated_at": now,
    }
    return Property(**(defaults | overrides))


def _make_extraction_job(user_id=None, organization_id=None, **overrides) -> ExtractionJob:
    now = datetime.now(timezone.utc)
    defaults = {
        "id": uuid4(),
        "user_id": user_id or uuid4(),
        "organization_id": organization_id or uuid4(),
        "status": ExtractionJobStatus.PENDING,
        "document_keys": ["docs/file1.pdf", "docs/file2.pdf"],
        "listing_type": "sale",
        "typology": "apartment",
        "property_id": None,
        "error_message": None,
        "created_at": now,
        "updated_at": now,
    }
    return ExtractionJob(**(defaults | overrides))


async def test_save_and_get_extraction_job(organization_repo, extraction_job_repo):
    org = await organization_repo.save(_make_organization())
    job = _make_extraction_job(organization_id=org.id)

    saved = await extraction_job_repo.save(job)
    assert saved.id == job.id
    assert saved.status == ExtractionJobStatus.PENDING
    assert saved.document_keys == ["docs/file1.pdf", "docs/file2.pdf"]

    fetched = await extraction_job_repo.get_by_id(job.id)
    assert fetched is not None
    assert fetched.listing_type == "sale"
    assert fetched.typology == "apartment"


async def test_list_by_organization(organization_repo, extraction_job_repo):
    org = await organization_repo.save(_make_organization())

    for _ in range(3):
        await extraction_job_repo.save(_make_extraction_job(organization_id=org.id))

    jobs = await extraction_job_repo.list_by_organization(org.id)
    assert len(jobs) == 3


async def test_update_status(organization_repo, extraction_job_repo):
    org = await organization_repo.save(_make_organization())
    job = _make_extraction_job(organization_id=org.id)
    await extraction_job_repo.save(job)

    job.mark_processing()
    updated = await extraction_job_repo.update(job)
    assert updated.status == ExtractionJobStatus.PROCESSING

    fetched = await extraction_job_repo.get_by_id(job.id)
    assert fetched.status == ExtractionJobStatus.PROCESSING


async def test_update_completed_with_property(
    organization_repo, user_repo, property_repo, extraction_job_repo
):
    org = await organization_repo.save(_make_organization())
    user = await user_repo.save(_make_user(org.id))
    prop = await property_repo.save(_make_property(org.id))

    job = _make_extraction_job(user_id=user.id, organization_id=org.id)
    await extraction_job_repo.save(job)

    job.mark_completed(prop.id)
    updated = await extraction_job_repo.update(job)

    assert updated.status == ExtractionJobStatus.COMPLETED
    assert updated.property_id == prop.id


async def test_update_failed(organization_repo, extraction_job_repo):
    org = await organization_repo.save(_make_organization())
    job = _make_extraction_job(organization_id=org.id)
    await extraction_job_repo.save(job)

    job.mark_failed("Something went wrong")
    updated = await extraction_job_repo.update(job)

    assert updated.status == ExtractionJobStatus.FAILED
    assert updated.error_message == "Something went wrong"


async def test_get_nonexistent_job(extraction_job_repo):
    result = await extraction_job_repo.get_by_id(uuid4())
    assert result is None
