from __future__ import annotations

from uuid import UUID

from properties.application.events.property_event import emit_property_updated
from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.exceptions import PropertyNotFoundError
from properties.domain.models.property import Property
from shared.events.ports import EventPublisher


class UpdatePropertyAddress:
    """Patch a property's `address`, bump aggregate_version, and emit
    PROPERTY_UPDATED.v1.

    Mirrors the UpdatePropertyOwnerContact update-style pattern, with two
    differences:
      1. Org-scope check is in-line (matches PublishProperty), not via the
         route-level `_verify_property_ownership` helper.
      2. Short-circuits when the stripped new value matches the current
         (post-normalization) address — no write, no version bump, no
         event emission. Avoids redundant projector traffic on idempotent
         retries.
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
        address: str,
    ) -> Property:
        prop = await self.property_repo.get_by_id(property_id)
        if prop is None or prop.organization_id != organization_id:
            raise PropertyNotFoundError(str(property_id))

        old_address = prop.address
        prop.update_address(address)
        if prop.address == old_address:
            return prop

        await self.property_repo.update_address(property_id, prop.address)
        refreshed = await self.property_repo.bump_aggregate_version(property_id)
        await emit_property_updated(self.domain_event_publisher, refreshed)
        return refreshed
