from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from uuid import UUID, uuid4

import structlog

from properties.application.ports.document_storage import DocumentStorage
from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.exceptions import PropertyNotFoundError

log = structlog.get_logger()

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGES = 20


@dataclass
class PresignedImageFile:
    image_id: UUID
    s3_key: str
    upload_url: str


class GenerateImageUploadUrls:
    def __init__(
        self,
        image_storage: DocumentStorage,
        property_repo: PropertyRepository,
    ) -> None:
        self.image_storage = image_storage
        self.property_repo = property_repo

    async def execute(
        self,
        *,
        property_id: UUID,
        files: list[dict],
    ) -> list[PresignedImageFile]:
        prop = await self.property_repo.get_by_id(property_id)
        if not prop:
            raise PropertyNotFoundError(str(property_id))

        presigned = []
        for file_spec in files:
            image_id = uuid4()
            content_type = file_spec.get("content_type", "image/jpeg")
            filename = file_spec.get("filename", "image.jpg")
            ext = PurePosixPath(filename).suffix or ".jpg"
            s3_key = f"properties/{property_id}/images/{image_id}{ext}"

            upload_url = await self.image_storage.get_upload_url(
                key=s3_key,
                content_type=content_type,
            )
            presigned.append(
                PresignedImageFile(image_id=image_id, s3_key=s3_key, upload_url=upload_url)
            )

        log.info(
            "property_images.presign_generated",
            property_id=str(property_id),
            num_files=len(files),
        )
        return presigned
