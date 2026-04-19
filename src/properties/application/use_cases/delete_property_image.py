from __future__ import annotations

from uuid import UUID

import structlog

from properties.application.events.property_event import emit_property_updated
from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.exceptions import PropertyImageNotFoundError, PropertyNotFoundError
from properties.domain.models.property import Property
from shared.events.ports import EventPublisher

log = structlog.get_logger()


class DeletePropertyImage:
    def __init__(
        self,
        property_repo: PropertyRepository,
        domain_event_publisher: EventPublisher | None = None,
    ) -> None:
        self.property_repo = property_repo
        self.domain_event_publisher = domain_event_publisher

    async def execute(self, *, property_id: UUID, image_id: UUID) -> Property:
        prop = await self.property_repo.get_by_id(property_id)
        if not prop:
            raise PropertyNotFoundError(str(property_id))

        image = prop.get_image(image_id)
        if not image:
            raise PropertyImageNotFoundError(str(image_id))

        await self.property_repo.delete_image(prop, image_id)
        refreshed = await self.property_repo.bump_aggregate_version(property_id)
        log.info(
            "property_images.deleted",
            property_id=str(property_id),
            image_id=str(image_id),
        )
        await emit_property_updated(self.domain_event_publisher, refreshed)
        return refreshed
