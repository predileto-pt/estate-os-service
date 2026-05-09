from uuid import UUID

from listings.application.ports.repositories.property_listing_repository import (
    PropertyListingRepository,
)
from listings.domain.exceptions import PropertyNotFoundError
from listings.domain.models import PropertyStatus
from listings.domain.property_listing import PropertyListing


class GetProperty:
    def __init__(self, property_listing_repo: PropertyListingRepository) -> None:
        self._property_listing_repo = property_listing_repo

    async def execute(self, property_id: UUID) -> PropertyListing:
        prop = await self._property_listing_repo.get_by_id(property_id)
        # The legacy `ListingRepository.get_by_id` filtered to ACTIVE at
        # the SQL level. The new repo doesn't (it serves the listings
        # worker too, which needs DRAFT rows). Enforce the public-facing
        # ACTIVE check here.
        if prop is None or prop.status != PropertyStatus.ACTIVE:
            raise PropertyNotFoundError(str(property_id))
        return prop
