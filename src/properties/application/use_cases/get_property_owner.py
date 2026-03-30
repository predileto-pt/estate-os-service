from uuid import UUID

from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.exceptions import PropertyNotFoundError, PropertyOwnerNotFoundError
from properties.domain.models.property_owner import PropertyOwner


class GetPropertyOwner:
    def __init__(self, property_repo: PropertyRepository) -> None:
        self.property_repo = property_repo

    async def execute(self, *, property_id: UUID, owner_id: UUID) -> PropertyOwner:
        prop = await self.property_repo.get_by_id(property_id)
        if not prop:
            raise PropertyNotFoundError(str(property_id))
        owner = prop.get_owner(owner_id)
        if not owner:
            raise PropertyOwnerNotFoundError(str(owner_id))
        return owner
