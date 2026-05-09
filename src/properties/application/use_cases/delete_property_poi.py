from __future__ import annotations

from uuid import UUID

from properties.application.ports.repositories.property_poi_repository import (
    PropertyPoiRepository,
)
from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.exceptions import PropertyNotFoundError


class DeletePropertyPoi:
    """Remove one POI. Inline org-scope + cross-property checks (matches
    `UpdatePropertyPoi`). Bumps `aggregate_version` so the listings
    projector picks up the change. Missing POI raises
    `PropertyNotFoundError` (not idempotent — matches the
    `delete_property` precedent in this codebase).
    """

    def __init__(
        self,
        property_repo: PropertyRepository,
        property_poi_repo: PropertyPoiRepository,
    ) -> None:
        self.property_repo = property_repo
        self.property_poi_repo = property_poi_repo

    async def execute(self, *, property_id: UUID, organization_id: UUID, poi_id: UUID) -> None:
        prop = await self.property_repo.get_by_id(property_id)
        if prop is None or prop.organization_id != organization_id:
            raise PropertyNotFoundError(str(property_id))

        existing = await self.property_poi_repo.get_by_id(poi_id)
        if existing is None or existing.property_id != property_id:
            raise PropertyNotFoundError(str(poi_id))

        await self.property_poi_repo.delete(poi_id)
        await self.property_repo.bump_aggregate_version(property_id)
