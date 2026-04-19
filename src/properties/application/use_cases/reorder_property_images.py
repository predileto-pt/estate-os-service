from __future__ import annotations

from uuid import UUID

import structlog

from properties.application.events.property_event import emit_property_updated
from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.exceptions import PropertyNotFoundError
from properties.domain.models.property import Property
from shared.events.ports import EventPublisher

log = structlog.get_logger()


class ReorderPropertyImages:
    def __init__(
        self,
        property_repo: PropertyRepository,
        domain_event_publisher: EventPublisher | None = None,
    ) -> None:
        self.property_repo = property_repo
        self.domain_event_publisher = domain_event_publisher

    async def execute(self, *, property_id: UUID, image_ids: list[UUID]) -> Property:
        prop = await self.property_repo.get_by_id(property_id)
        if not prop:
            raise PropertyNotFoundError(str(property_id))

        existing_ids = {i.id for i in prop.images}
        provided_ids = set(image_ids)
        if existing_ids != provided_ids:
            raise ValueError("image_ids must contain exactly all image IDs for this property")

        image_orders = [(image_id, order) for order, image_id in enumerate(image_ids)]
        await self.property_repo.update_image_orders(prop, image_orders)
        refreshed = await self.property_repo.bump_aggregate_version(property_id)
        log.info(
            "property_images.reordered",
            property_id=str(property_id),
            count=len(image_ids),
        )
        await emit_property_updated(self.domain_event_publisher, refreshed)
        return refreshed
