from uuid import UUID

from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.exceptions import PropertyNotFoundError, PropertyOwnerNotFoundError
from properties.domain.models.property import Property


class UpdatePropertyOwnerContact:
    def __init__(self, property_repo: PropertyRepository) -> None:
        self.property_repo = property_repo

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

        return await self.property_repo.update_owner(prop, owner)
