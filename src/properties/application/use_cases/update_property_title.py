from __future__ import annotations

from uuid import UUID

from properties.application.events.property_event import emit_property_updated
from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.exceptions import PropertyNotFoundError
from properties.domain.models.property import Property
from shared.events.ports import EventPublisher


class UpdatePropertyTitle:
    """Patch a property's `title`, bump aggregate_version, and emit
    PROPERTY_UPDATED.v1.

    Mirrors `UpdatePropertyAddress`: short-circuits when the stripped new
    value matches the current title — no write, no version bump, no
    event emission.
    """

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
        property_id: UUID,
        organization_id: UUID,
        title: str,
    ) -> Property:
        prop = await self.property_repo.get_by_id(property_id)
        if prop is None or prop.organization_id != organization_id:
            raise PropertyNotFoundError(str(property_id))

        old_title = prop.title
        prop.update_title(title)
        if prop.title == old_title:
            return prop

        await self.property_repo.update_title(property_id, prop.title)
        refreshed = await self.property_repo.bump_aggregate_version(property_id)
        await emit_property_updated(self.domain_event_publisher, refreshed)
        return refreshed
