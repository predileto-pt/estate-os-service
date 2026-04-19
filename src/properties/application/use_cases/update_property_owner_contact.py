from uuid import UUID

from properties.application.events.property_event import emit_property_updated
from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.exceptions import PropertyNotFoundError, PropertyOwnerNotFoundError
from properties.domain.models.property import Property
from shared.events.ports import EventPublisher


class UpdatePropertyOwnerContact:
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
        owner_id: UUID,
        email: str | None,
        phone_number: str | None,
    ) -> Property:
        prop = await self.property_repo.get_by_id(property_id)
        if not prop:
            raise PropertyNotFoundError(str(property_id))

        owner = next((o for o in prop.owners if o.id == owner_id), None)
        if not owner:
            raise PropertyOwnerNotFoundError(str(owner_id))

        if email is not None and email != owner.email:
            owner.email = email
            owner.email_verified = False

        if phone_number is not None and phone_number != owner.phone_number:
            owner.phone_number = phone_number
            owner.phone_verified = False

        await self.property_repo.update_owner(prop, owner)
        refreshed = await self.property_repo.bump_aggregate_version(property_id)
        await emit_property_updated(self.domain_event_publisher, refreshed)
        return refreshed
