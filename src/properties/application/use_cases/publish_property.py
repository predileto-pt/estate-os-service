from __future__ import annotations

from uuid import UUID

from properties.application.events.property_event import emit_property_published
from properties.application.ports.repositories.property_poi_repository import (
    PropertyPoiRepository,
)
from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.exceptions import PropertyNotFoundError
from properties.domain.models.property import Property, PropertyStatus
from shared.events.ports import EventPublisher


class PublishProperty:
    """Flip a property from DRAFT (or WITHDRAWN) to ACTIVE and broadcast
    PROPERTY_PUBLISHED.v1.

    Mirrors the UpdatePropertyOwnerContact update-style pattern:
      1. Load the aggregate (with inline org-scope check).
      2. Invoke the domain method — it enforces publishability invariants.
      3. Persist the status via the targeted repo port.
      4. Atomically bump aggregate_version through the port's canonical path.
      5. Emit PROPERTY_PUBLISHED.v1 via the shared emit helper (log-and-swallow).

    The published event carries POIs from the catalog (spec
    `2026-05-listing-semantic-search`): the listings projector seeds
    `property_listings.pois` from this snapshot so the embedding handler
    can render `NEARBY:` for the initial embedding. POI repo is optional
    — when absent the snapshot omits POIs and listings starts with
    empty pois on the row.
    """

    def __init__(
        self,
        property_repo: PropertyRepository,
        domain_event_publisher: EventPublisher | None = None,
        property_poi_repo: PropertyPoiRepository | None = None,
    ) -> None:
        self.property_repo = property_repo
        self.domain_event_publisher = domain_event_publisher
        self.property_poi_repo = property_poi_repo

    async def execute(self, *, property_id: UUID, organization_id: UUID) -> Property:
        prop = await self.property_repo.get_by_id(property_id)
        if prop is None or prop.organization_id != organization_id:
            raise PropertyNotFoundError(str(property_id))

        prop.publish()

        await self.property_repo.update_status(property_id, PropertyStatus.ACTIVE)
        refreshed = await self.property_repo.bump_aggregate_version(property_id)
        pois = (
            await self.property_poi_repo.list_by_property(property_id)
            if self.property_poi_repo is not None
            else None
        )
        await emit_property_published(self.domain_event_publisher, refreshed, pois)
        return refreshed
