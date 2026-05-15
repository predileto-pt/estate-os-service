from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import structlog

from properties.application.events.property_event import emit_property_updated
from properties.application.ports.document_storage import DocumentStorage
from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.exceptions import PropertyNotFoundError
from properties.domain.models.property import Property
from properties.domain.models.property_image import PropertyImage
from shared.events.ports import EventPublisher

log = structlog.get_logger()

MAX_IMAGES = 20


class RecordPropertyImage:
    def __init__(
        self,
        property_repo: PropertyRepository,
        image_storage: DocumentStorage,
        images_cdn_base_url: str = "",
        domain_event_publisher: EventPublisher | None = None,
    ) -> None:
        self.property_repo = property_repo
        self.image_storage = image_storage
        # When non-empty, `execute` derives the public URL by concatenating
        # this base with the s3_key (skipping any S3 round-trip). Empty
        # is the LocalStack dev path — fall through to image_storage's
        # `get_public_url` which returns the LocalStack endpoint URL.
        # Wiring happens in a follow-up commit.
        self.images_cdn_base_url = images_cdn_base_url
        self.domain_event_publisher = domain_event_publisher

    async def execute(
        self,
        *,
        property_id: UUID,
        image_id: UUID,
        s3_key: str,
        filename: str,
        content_type: str,
        size_bytes: int,
    ) -> Property:
        prop = await self.property_repo.get_by_id(property_id)
        if not prop:
            raise PropertyNotFoundError(str(property_id))

        if len(prop.images) >= MAX_IMAGES:
            raise ValueError(f"Property already has {MAX_IMAGES} images (maximum)")

        exists = await self.image_storage.verify_exists(s3_key)
        if not exists:
            raise FileNotFoundError(f"File not found in storage: {s3_key}")

        now = datetime.now(timezone.utc)
        # Compute the URL once at upload time and persist it on the row.
        # Read path returns it as-is — no S3 round-trip, no coupling to
        # storage config. In production the URL points at the CloudFront
        # CDN (https://images.predileto.pt/<key>); in dev it points at
        # LocalStack (http://localhost:4566/property-images/<key>). The
        # underlying S3 bucket is private in both environments. If the
        # CDN domain ever changes, run a one-shot UPDATE on this column.
        if self.images_cdn_base_url:
            public_url = f"{self.images_cdn_base_url.rstrip('/')}/{s3_key}"
        else:
            public_url = self.image_storage.get_public_url(s3_key)
        image = PropertyImage(
            id=image_id,
            property_id=property_id,
            s3_key=s3_key,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            display_order=len(prop.images),
            created_at=now,
            updated_at=now,
            url=public_url,
        )

        await self.property_repo.save_image(prop, image)
        refreshed = await self.property_repo.bump_aggregate_version(property_id)
        log.info(
            "property_images.recorded",
            property_id=str(property_id),
            image_id=str(image_id),
        )
        await emit_property_updated(self.domain_event_publisher, refreshed)
        return refreshed
