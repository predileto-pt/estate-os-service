from __future__ import annotations

from uuid import UUID

from listings.application.ports.listing_repository import ListingRepository, PropertyFilters
from listings.domain.models import ListedProperty


class ListOrgActiveListings:
    """List ACTIVE listings for one organization. Mirrors `ListProperties`
    (the public-endpoint use case) but threads `organization_id` through
    to the repo. Permission enforcement happens at the route layer via
    `require_org_member` — the use case is permission-agnostic.
    """

    def __init__(self, listing_repo: ListingRepository) -> None:
        self._listing_repo = listing_repo

    async def execute(
        self, *, organization_id: UUID, filters: PropertyFilters
    ) -> tuple[list[ListedProperty], int]:
        properties = await self._listing_repo.list_active_for_organization(organization_id, filters)
        total = await self._listing_repo.count_active_for_organization(organization_id, filters)
        return properties, total
