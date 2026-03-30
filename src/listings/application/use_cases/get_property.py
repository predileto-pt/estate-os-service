from uuid import UUID

from listings.application.ports.listing_repository import ListingRepository
from listings.domain.exceptions import PropertyNotFoundError
from listings.domain.models import ListedProperty


class GetProperty:
    def __init__(self, listing_repo: ListingRepository) -> None:
        self._listing_repo = listing_repo

    async def execute(self, property_id: UUID) -> ListedProperty:
        prop = await self._listing_repo.get_by_id(property_id)
        if not prop:
            raise PropertyNotFoundError(str(property_id))
        return prop
