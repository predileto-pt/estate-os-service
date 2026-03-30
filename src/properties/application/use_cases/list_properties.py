from uuid import UUID

from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.models.property import Property


class ListProperties:
    def __init__(self, property_repo: PropertyRepository) -> None:
        self.property_repo = property_repo

    async def execute(self, *, organization_id: str) -> list[Property]:
        return await self.property_repo.list_by_organization(UUID(organization_id))
