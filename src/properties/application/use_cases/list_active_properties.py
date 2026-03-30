from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.models.property import Property


class ListActiveProperties:
    def __init__(self, property_repo: PropertyRepository) -> None:
        self.property_repo = property_repo

    async def execute(self) -> list[Property]:
        return await self.property_repo.list_active()
