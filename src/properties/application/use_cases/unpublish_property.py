from __future__ import annotations

from uuid import UUID

from properties.application.events.property_event import emit_property_unpublished
from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.exceptions import PropertyNotFoundError
from properties.domain.models.property import Property, PropertyStatus
from shared.events.ports import EventPublisher


class UnpublishProperty:
    """Flip a property from ACTIVE back to DRAFT and broadcast
    PROPERTY_UNPUBLISHED.v1.

    Symmetric to `PublishProperty`:
      1. Load the aggregate (with inline org-scope check).
      2. Invoke the domain method — raises `PropertyNotUnpublishableError`
         when the property isn't ACTIVE.
      3. Persist the new status (DRAFT) via `update_status`.
      4. Bump aggregate_version through the canonical port path.
      5. Emit PROPERTY_UNPUBLISHED.v1 (minimal id/version payload).

    The listings projector subscribes to the event and deletes the
    `property_listings` row — taking the property off the public site.
    """

    def __init__(
        self,
        property_repo: PropertyRepository,
        domain_event_publisher: EventPublisher | None = None,
    ) -> None:
        self.property_repo = property_repo
        self.domain_event_publisher = domain_event_publisher

    async def execute(self, *, property_id: UUID, organization_id: UUID) -> Property:
        prop = await self.property_repo.get_by_id(property_id)
        if prop is None or prop.organization_id != organization_id:
            raise PropertyNotFoundError(str(property_id))

        prop.unpublish()  # domain invariant — raises if not ACTIVE

        await self.property_repo.update_status(property_id, PropertyStatus.DRAFT)
        refreshed = await self.property_repo.bump_aggregate_version(property_id)
        await emit_property_unpublished(self.domain_event_publisher, refreshed)
        return refreshed
