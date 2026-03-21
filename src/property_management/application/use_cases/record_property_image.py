from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import structlog

from property_management.application.ports.document_storage import DocumentStorage
from property_management.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from property_management.domain.exceptions import PropertyNotFoundError
from property_management.domain.models.property import Property
from property_management.domain.models.property_image import PropertyImage

log = structlog.get_logger()

MAX_IMAGES = 20


class RecordPropertyImage:
    def __init__(
        self,
        property_repo: PropertyRepository,
        document_storage: DocumentStorage,
    ) -> None:
        self.property_repo = property_repo
        self.document_storage = document_storage

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
        )

        prop = await self.property_repo.save_image(prop, image)
        log.info(
            "property_images.recorded",
            property_id=str(property_id),
            image_id=str(image_id),
        )
        return prop
