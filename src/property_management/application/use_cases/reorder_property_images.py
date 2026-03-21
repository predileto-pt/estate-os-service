from __future__ import annotations

from uuid import UUID

import structlog

from property_management.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from property_management.domain.exceptions import PropertyNotFoundError
from property_management.domain.models.property import Property

log = structlog.get_logger()


class ReorderPropertyImages:
    def __init__(self, property_repo: PropertyRepository) -> None:
        self.property_repo = property_repo

    async def execute(self, *, property_id: UUID, image_ids: list[UUID]) -> Property:
        prop = await self.property_repo.get_by_id(property_id)
        if not prop:
            raise PropertyNotFoundError(str(property_id))

        existing_ids = {i.id for i in prop.images}
        provided_ids = set(image_ids)
        if existing_ids != provided_ids:
            raise ValueError("image_ids must contain exactly all image IDs for this property")

        image_orders = [(image_id, order) for order, image_id in enumerate(image_ids)]
        prop = await self.property_repo.update_image_orders(prop, image_orders)
        log.info(
            "property_images.reordered",
            property_id=str(property_id),
            count=len(image_ids),
        )
        return prop
