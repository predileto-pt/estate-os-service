from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import structlog

from property_management.application.ports.event_bus import EventBus
from property_management.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from property_management.domain.events import PropertyCreated
from property_management.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)

log = structlog.get_logger()


class CreateProperty:
    def __init__(
        self,
        property_repo: PropertyRepository,
        discovery_event_bus: EventBus | None = None,
    ) -> None:
        self.property_repo = property_repo
        self.discovery_event_bus = discovery_event_bus

    async def execute(
        self,
        *,
        organization_id: str,
        address: str,
        listing_type: ListingType,
        typology: Typology,
        description: str | None = None,
    ) -> Property:
        now = datetime.now(timezone.utc)
        prop = Property(
            id=uuid4(),
            organization_id=UUID(organization_id),
            address=address,
            listing_type=listing_type,
            typology=typology,
            status=PropertyStatus.DRAFT,
            description=description,
            created_at=now,
            updated_at=now,
        )
        prop = await self.property_repo.save(prop)

        if self.discovery_event_bus:
            try:
                await self.discovery_event_bus.publish(PropertyCreated(property_id=str(prop.id)))
            except Exception:
                log.exception(
                    "create_property.discovery_event_failed",
                    property_id=str(prop.id),
                )

        return prop
