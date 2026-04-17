from uuid import UUID

from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.exceptions import PropertyNotFoundError
from properties.domain.models.property import Property


class GetProperty:
    def __init__(self, property_repo: PropertyRepository) -> None:
        self.property_repo = property_repo

    async def execute(self, *, property_id: UUID, organization_id: UUID | None = None) -> Property:
        prop = await self.property_repo.get_by_id(property_id)
        if not prop:
            raise PropertyNotFoundError(str(property_id))
        if organization_id is not None and str(prop.organization_id) != str(organization_id):
            # Don't leak existence of properties in other orgs.
            raise PropertyNotFoundError(str(property_id))
        return prop
