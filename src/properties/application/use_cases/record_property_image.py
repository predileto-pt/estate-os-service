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
        document_storage: DocumentStorage,
        domain_event_publisher: EventPublisher | None = None,
    ) -> None:
        self.property_repo = property_repo
        self.document_storage = document_storage
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

        exists = await self.document_storage.verify_exists(s3_key)
        if not exists:
            raise FileNotFoundError(f"File not found in storage: {s3_key}")

        now = datetime.now(timezone.utc)
        # Compute the public URL once, at upload time, and persist it on
        # the row. Read path returns it as-is — no S3 round-trip, no
        # coupling to storage config. Property images live in a public
        # bucket; if that ever changes, the upload flow is the single
        # place to revisit.
        public_url = self.document_storage.get_public_url(s3_key)
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
