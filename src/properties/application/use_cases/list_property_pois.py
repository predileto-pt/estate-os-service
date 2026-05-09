from __future__ import annotations

from uuid import UUID

from properties.application.ports.repositories.property_poi_repository import (
    PropertyPoiRepository,
)
from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.exceptions import PropertyNotFoundError
from properties.domain.models.property_poi import PropertyPoi


class ListPropertyPois:
    """Read-only listing of a property's POIs. Inline org-scope check
    (returns 404 on miss); then hands off to the POI repo. No
    aggregate_version bump — read-only.
    """

    def __init__(
        self,
        property_repo: PropertyRepository,
        property_poi_repo: PropertyPoiRepository,
    ) -> None:
        self.property_repo = property_repo
        self.property_poi_repo = property_poi_repo

    async def execute(self, *, property_id: UUID, organization_id: UUID) -> list[PropertyPoi]:
        prop = await self.property_repo.get_by_id(property_id)
        if prop is None or prop.organization_id != organization_id:
            raise PropertyNotFoundError(str(property_id))
        return await self.property_poi_repo.list_by_property(property_id)
