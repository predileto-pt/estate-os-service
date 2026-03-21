from __future__ import annotations

from uuid import UUID

import structlog

from property_management.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from property_management.domain.exceptions import PropertyImageNotFoundError, PropertyNotFoundError
from property_management.domain.models.property import Property

log = structlog.get_logger()


class DeletePropertyImage:
    def __init__(self, property_repo: PropertyRepository) -> None:
        self.property_repo = property_repo

    async def execute(self, *, property_id: UUID, image_id: UUID) -> Property:
        prop = await self.property_repo.get_by_id(property_id)
        if not prop:
            raise PropertyNotFoundError(str(property_id))

        image = prop.get_image(image_id)
        if not image:
            raise PropertyImageNotFoundError(str(image_id))

        prop = await self.property_repo.delete_image(prop, image_id)
        log.info(
            "property_images.deleted",
            property_id=str(property_id),
            image_id=str(image_id),
        )
        return prop
