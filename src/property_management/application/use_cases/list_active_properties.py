from property_management.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from property_management.domain.models.property import Property


class ListActiveProperties:
    def __init__(self, property_repo: PropertyRepository) -> None:
        self.property_repo = property_repo

    async def execute(self) -> list[Property]:
        return await self.property_repo.list_active()
