from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import structlog

from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from shared.events.base import DomainEvent as SharedDomainEvent
from shared.events.ports import EventPublisher
from shared.events.types import PROPERTY_CREATED_V1
from properties.domain.models.property import (
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
        domain_event_publisher: EventPublisher | None = None,
    ) -> None:
        self.property_repo = property_repo
        self.domain_event_publisher = domain_event_publisher

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

        if self.domain_event_publisher:
            try:
                await self.domain_event_publisher.publish(
                    SharedDomainEvent(
                        event_type=PROPERTY_CREATED_V1, data={"property_id": str(prop.id)}
                    )
                )
            except Exception:
                log.exception(
                    "create_property.domain_event_failed",
                    property_id=str(prop.id),
                )

        return prop
