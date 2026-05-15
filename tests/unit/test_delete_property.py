from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from properties.adapters.inmemory.inmemory_document_storage import InMemoryDocumentStorage
from properties.adapters.inmemory.inmemory_extraction_job_repo import (
    InMemoryExtractionJobRepository,
)
from properties.adapters.inmemory.inmemory_property_repo import InMemoryPropertyRepository
from properties.application.use_cases.delete_property import DeleteProperty
from properties.domain.exceptions import PropertyNotFoundError
from properties.domain.models.extraction_job import ExtractionJob, ExtractionJobStatus
from properties.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)
from properties.domain.models.property_image import PropertyImage

ORG_ID = UUID("00000000-0000-0000-0000-000000000010")
OTHER_ORG_ID = UUID("00000000-0000-0000-0000-000000000099")


def _make_property(num_images: int = 0) -> Property:
    now = datetime.now(timezone.utc)
    prop = Property(
        id=uuid4(),
        organization_id=ORG_ID,
        title="Test property",
        address="Rua das Flores 123",
        listing_type=ListingType.SALE,
        typology=Typology.APARTMENT,
        status=PropertyStatus.ACTIVE,
        description=None,
        created_at=now,
        updated_at=now,
    )
    for i in range(num_images):
        prop.add_image(
            PropertyImage(
                id=uuid4(),
                property_id=prop.id,
                s3_key=f"properties/{prop.id}/{i}.jpg",
                filename=f"{i}.jpg",
                content_type="image/jpeg",
                size_bytes=1024,
                display_order=i,
                created_at=now,
                updated_at=now,
            )
        )
    return prop


@pytest.fixture
def property_repo():
    return InMemoryPropertyRepository()


@pytest.fixture
def extraction_job_repo():
    return InMemoryExtractionJobRepository()


@pytest.fixture
def storage():
    return InMemoryDocumentStorage()


@pytest.fixture
def use_case(property_repo, extraction_job_repo, storage):
    return DeleteProperty(
        property_repo=property_repo,
        extraction_job_repo=extraction_job_repo,
        image_storage=storage,
    )


class TestDeleteProperty:
    async def test_deletes_property_with_no_images_or_jobs(self, use_case, property_repo):
        prop = _make_property()
        await property_repo.save(prop)

        await use_case.execute(property_id=prop.id, organization_id=ORG_ID)

        assert await property_repo.get_by_id(prop.id) is None

    async def test_deletes_s3_image_objects(self, use_case, property_repo, storage):
        prop = _make_property(num_images=3)
        await property_repo.save(prop)
        for image in prop.images:
            await storage.upload(image.s3_key, b"fake-jpeg", "image/jpeg")

        # Sanity: images exist in S3
        for image in prop.images:
            assert await storage.verify_exists(image.s3_key)

        await use_case.execute(property_id=prop.id, organization_id=ORG_ID)

        # All S3 objects gone
        for image in prop.images:
            assert not await storage.verify_exists(image.s3_key)
        assert await property_repo.get_by_id(prop.id) is None

    async def test_deletes_linked_extraction_jobs(
        self, use_case, property_repo, extraction_job_repo
    ):
        prop = _make_property()
        await property_repo.save(prop)

        # Two jobs linked to this property
        for _ in range(2):
            await extraction_job_repo.save(
                ExtractionJob(
                    id=uuid4(),
                    user_id=uuid4(),
                    organization_id=ORG_ID,
                    status=ExtractionJobStatus.COMPLETED,
                    property_id=prop.id,
                    document_keys=["foo.pdf"],
                )
            )
        # An unrelated job for a different property — must NOT be deleted
        unrelated = ExtractionJob(
            id=uuid4(),
            user_id=uuid4(),
            organization_id=ORG_ID,
            status=ExtractionJobStatus.COMPLETED,
            property_id=uuid4(),
            document_keys=["bar.pdf"],
        )
        await extraction_job_repo.save(unrelated)

        await use_case.execute(property_id=prop.id, organization_id=ORG_ID)

        all_jobs = await extraction_job_repo.list_by_organization(ORG_ID)
        assert len(all_jobs) == 1
        assert all_jobs[0].id == unrelated.id

    async def test_property_not_found_raises(self, use_case):
        with pytest.raises(PropertyNotFoundError):
            await use_case.execute(property_id=uuid4(), organization_id=ORG_ID)

    async def test_wrong_organization_raises_not_found(self, use_case, property_repo):
        prop = _make_property()
        await property_repo.save(prop)

        with pytest.raises(PropertyNotFoundError):
            await use_case.execute(property_id=prop.id, organization_id=OTHER_ORG_ID)

        # Property must still exist
        assert await property_repo.get_by_id(prop.id) is not None

    async def test_s3_delete_failure_does_not_block_db_delete(
        self, property_repo, extraction_job_repo
    ):
        class FailingStorage(InMemoryDocumentStorage):
            async def delete(self, key: str) -> None:
                raise RuntimeError("S3 down")

        storage = FailingStorage()
        uc = DeleteProperty(
            property_repo=property_repo,
            extraction_job_repo=extraction_job_repo,
            image_storage=storage,
        )

        prop = _make_property(num_images=2)
        await property_repo.save(prop)

        # Should NOT raise — S3 errors are best-effort logged
        await uc.execute(property_id=prop.id, organization_id=ORG_ID)
        assert await property_repo.get_by_id(prop.id) is None
