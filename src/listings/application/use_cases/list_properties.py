from listings.application.ports.listing_repository import ListingRepository, PropertyFilters
from listings.domain.models import ListedProperty


class ListProperties:
    def __init__(self, listing_repo: ListingRepository) -> None:
        self._listing_repo = listing_repo

    async def execute(self, filters: PropertyFilters) -> tuple[list[ListedProperty], int]:
        properties = await self._listing_repo.list_active(filters)
        total = await self._listing_repo.count_active(filters)
        return properties, total
