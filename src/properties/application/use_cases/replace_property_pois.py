from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from properties.application.ports.repositories.property_poi_repository import (
    PropertyPoiRepository,
)
from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.exceptions import PropertyNotFoundError
from properties.domain.models.property_poi import PoiCategory, PropertyPoi


@dataclass(frozen=True)
class PoiInput:
    """Per-row payload for a replace operation. The use case wraps each
    of these in a `PropertyPoi` with `manually_edited=True` and a fresh
    id before persisting.
    """

    category: PoiCategory
    name: str
    distance_meters: float
    latitude: float
    longitude: float
    place_type: str | None = None
    place_id: str | None = None
    metadata: dict | None = None
    # Place-details fields (spec 2026-05-poi-rich-metadata). Manual
    # entry can attach these; defaults match the auto-discovery
    # not-yet-enriched state.
    address: str | None = None
    image_urls: list[str] | None = None
    reviews: list[dict] | None = None


class ReplacePropertyPois:
    """Replace the entire POI catalog for one property. Empty list is
    valid — clears the catalog. Every persisted row gets
    `manually_edited=True` so future enrichment runs respect the agent's
    work.
    """

    def __init__(
        self,
        property_repo: PropertyRepository,
        property_poi_repo: PropertyPoiRepository,
    ) -> None:
        self.property_repo = property_repo
        self.property_poi_repo = property_poi_repo

    async def execute(
        self,
        *,
        property_id: UUID,
        organization_id: UUID,
        pois: list[PoiInput],
    ) -> list[PropertyPoi]:
        prop = await self.property_repo.get_by_id(property_id)
        if prop is None or prop.organization_id != organization_id:
            raise PropertyNotFoundError(str(property_id))

        domain_pois = [
            PropertyPoi(
                id=uuid4(),
                property_id=property_id,
                category=poi.category,
                name=poi.name,
                distance_meters=poi.distance_meters,
                latitude=poi.latitude,
                longitude=poi.longitude,
                place_type=poi.place_type,
                place_id=poi.place_id,
                metadata=poi.metadata or {},
                manually_edited=True,
                address=poi.address,
                image_urls=list(poi.image_urls) if poi.image_urls is not None else [],
                reviews=poi.reviews,
            )
            for poi in pois
        ]

        persisted = await self.property_poi_repo.replace_for_property(
            property_id=property_id, pois=domain_pois
        )
        await self.property_repo.bump_aggregate_version(property_id)
        return persisted
