from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from properties.adapters.inmemory.inmemory_document_storage import InMemoryDocumentStorage
from properties.adapters.inmemory.inmemory_property_repo import InMemoryPropertyRepository
from properties.application.use_cases.record_property_image import RecordPropertyImage
from properties.domain.exceptions import PropertyNotFoundError
from properties.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)


ORG_ID = UUID("00000000-0000-0000-0000-000000000010")


def _make_property() -> Property:
    now = datetime.now(timezone.utc)
    return Property(
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


class SpyStorage(InMemoryDocumentStorage):
    """Wraps the in-memory storage with a counter so tests can assert
    `get_public_url` was or wasn't called on the URL-build path."""

    def __init__(self) -> None:
        super().__init__()
        self.get_public_url_calls: list[str] = []

    def get_public_url(self, key: str) -> str:
        self.get_public_url_calls.append(key)
        return super().get_public_url(key)


async def _seed_uploaded(storage: SpyStorage, key: str) -> None:
    await storage.upload(key=key, data=b"fake-bytes", content_type="image/jpeg")


async def test_record_property_image_uses_cdn_base_url_when_set() -> None:
    """Prod path: `images_cdn_base_url` is set → URL is a pure string
    concat, `get_public_url` is never called (no S3 round-trip)."""

    storage = SpyStorage()
    repo = InMemoryPropertyRepository()
    prop = _make_property()
    await repo.save(prop)

    image_id = uuid4()
    s3_key = f"properties/{prop.id}/images/{image_id}.jpg"
    await _seed_uploaded(storage, s3_key)

    uc = RecordPropertyImage(
        property_repo=repo,
        image_storage=storage,
        images_cdn_base_url="https://images.predileto.pt",
    )

    refreshed = await uc.execute(
        property_id=prop.id,
        image_id=image_id,
        s3_key=s3_key,
        filename=f"{image_id}.jpg",
        content_type="image/jpeg",
        size_bytes=1024,
    )

    assert len(refreshed.images) == 1
    image = refreshed.images[0]
    assert image.url == f"https://images.predileto.pt/{s3_key}"
    # Critical: prod path skips the S3-coupled URL builder entirely.
    assert storage.get_public_url_calls == []


async def test_record_property_image_falls_back_to_get_public_url_when_base_empty() -> None:
    """Dev/LocalStack path: empty base URL → calls `image_storage.get_public_url`
    so the stored URL points at whatever the storage adapter exposes
    (LocalStack `http://localhost:4566/...` in real dev)."""

    storage = SpyStorage()
    repo = InMemoryPropertyRepository()
    prop = _make_property()
    await repo.save(prop)

    image_id = uuid4()
    s3_key = f"properties/{prop.id}/images/{image_id}.jpg"
    await _seed_uploaded(storage, s3_key)

    uc = RecordPropertyImage(
        property_repo=repo,
        image_storage=storage,
        images_cdn_base_url="",
    )

    refreshed = await uc.execute(
        property_id=prop.id,
        image_id=image_id,
        s3_key=s3_key,
        filename=f"{image_id}.jpg",
        content_type="image/jpeg",
        size_bytes=1024,
    )

    assert refreshed.images[0].url == f"https://fake-public-url.test/{s3_key}"
    assert storage.get_public_url_calls == [s3_key]


async def test_record_property_image_strips_trailing_slash_on_base_url() -> None:
    """Operator may paste the CDN base URL with or without trailing slash;
    use case normalizes."""

    storage = SpyStorage()
    repo = InMemoryPropertyRepository()
    prop = _make_property()
    await repo.save(prop)

    image_id = uuid4()
    s3_key = f"properties/{prop.id}/images/{image_id}.jpg"
    await _seed_uploaded(storage, s3_key)

    uc = RecordPropertyImage(
        property_repo=repo,
        image_storage=storage,
        images_cdn_base_url="https://images.predileto.pt/",  # trailing slash
    )

    refreshed = await uc.execute(
        property_id=prop.id,
        image_id=image_id,
        s3_key=s3_key,
        filename=f"{image_id}.jpg",
        content_type="image/jpeg",
        size_bytes=1024,
    )

    assert refreshed.images[0].url == f"https://images.predileto.pt/{s3_key}"


async def test_record_property_image_raises_when_property_missing() -> None:
    storage = SpyStorage()
    repo = InMemoryPropertyRepository()

    uc = RecordPropertyImage(
        property_repo=repo,
        image_storage=storage,
        images_cdn_base_url="https://images.predileto.pt",
    )

    with pytest.raises(PropertyNotFoundError):
        await uc.execute(
            property_id=uuid4(),
            image_id=uuid4(),
            s3_key="properties/missing/img.jpg",
            filename="img.jpg",
            content_type="image/jpeg",
            size_bytes=1024,
        )


async def test_record_property_image_raises_when_file_not_uploaded() -> None:
    """The use case verifies the S3 object exists before recording —
    catches a malicious client posting a fake s3_key without uploading."""

    storage = SpyStorage()
    repo = InMemoryPropertyRepository()
    prop = _make_property()
    await repo.save(prop)

    uc = RecordPropertyImage(
        property_repo=repo,
        image_storage=storage,
        images_cdn_base_url="https://images.predileto.pt",
    )

    with pytest.raises(FileNotFoundError):
        await uc.execute(
            property_id=prop.id,
            image_id=uuid4(),
            s3_key="properties/whatever/never-uploaded.jpg",
            filename="x.jpg",
            content_type="image/jpeg",
            size_bytes=1024,
        )
