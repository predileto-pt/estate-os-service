from __future__ import annotations

from uuid import UUID

from listings.application.ports.repositories.property_listing_repository import (
    PropertyListingRepository,
)
from listings.domain.property_filters import PropertyFilters
from listings.domain.property_listing import PropertyListing


class ListOrgActiveListings:
    """List ACTIVE listings for one organization. Mirrors `ListProperties`
    (the public-endpoint use case) but threads `organization_id` through
    to the repo. Permission enforcement happens at the route layer via
    `require_org_member` — the use case is permission-agnostic.
    """

    def __init__(self, property_listing_repo: PropertyListingRepository) -> None:
        self._property_listing_repo = property_listing_repo

    async def execute(
        self, *, organization_id: UUID, filters: PropertyFilters
    ) -> tuple[list[PropertyListing], int]:
        properties = await self._property_listing_repo.list_active_for_organization(
            organization_id, filters
        )
        total = await self._property_listing_repo.count_active_for_organization(
            organization_id, filters
        )
        return properties, total
