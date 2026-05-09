"""Public list endpoint use case — reads from the `property_listings`
projection via `PropertyListingRepository` (collapsed from the legacy
`ListingRepository` over the live `properties` table)."""

from listings.application.ports.repositories.property_listing_repository import (
    PropertyListingRepository,
)
from listings.domain.property_filters import PropertyFilters
from listings.domain.property_listing import PropertyListing


class ListProperties:
    def __init__(self, property_listing_repo: PropertyListingRepository) -> None:
        self._property_listing_repo = property_listing_repo

    async def execute(self, filters: PropertyFilters) -> tuple[list[PropertyListing], int]:
        properties = await self._property_listing_repo.list_active(filters)
        total = await self._property_listing_repo.count_active(filters)
        return properties, total
