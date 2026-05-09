from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from properties.application.ports.repositories.property_poi_repository import (
    PropertyPoiRepository,
)
from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.exceptions import PropertyNotFoundError
from properties.domain.models.property_poi import PoiCategory, PropertyPoi


@dataclass(frozen=True)
class PoiPatch:
    """Optional fields for a PATCH operation. None means 'leave unchanged'."""

    category: PoiCategory | None = None
    name: str | None = None
    distance_meters: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    place_type: str | None = None
    place_id: str | None = None
    metadata: dict | None = None
    # Place-details fields (spec 2026-05-poi-rich-metadata). Optional
    # so PATCH can override Phase 2 results if needed.
    address: str | None = None
    image_urls: list[str] | None = None
    reviews: list[dict] | None = None
    # Sentinel: True when the PATCH explicitly cleared `reviews` to
    # None (vs the field being omitted from the request body). Without
    # this we can't distinguish "leave unchanged" from "set to null".
    clear_reviews: bool = False


class UpdatePropertyPoi:
    """PATCH semantics on a single POI row. Sets `manually_edited=True`.
    Cross-property defense: 404 if the POI exists but belongs to a
    different property (never let a caller mutate a POI by guessing its
    id under the wrong property URL).
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
        poi_id: UUID,
        patch: PoiPatch,
    ) -> PropertyPoi:
        prop = await self.property_repo.get_by_id(property_id)
        if prop is None or prop.organization_id != organization_id:
            raise PropertyNotFoundError(str(property_id))

        existing = await self.property_poi_repo.get_by_id(poi_id)
        if existing is None or existing.property_id != property_id:
            raise PropertyNotFoundError(str(poi_id))

        updated = PropertyPoi(
            id=existing.id,
            property_id=existing.property_id,
            category=patch.category if patch.category is not None else existing.category,
            name=patch.name if patch.name is not None else existing.name,
            distance_meters=(
                patch.distance_meters
                if patch.distance_meters is not None
                else existing.distance_meters
            ),
            latitude=patch.latitude if patch.latitude is not None else existing.latitude,
            longitude=patch.longitude if patch.longitude is not None else existing.longitude,
            place_type=patch.place_type if patch.place_type is not None else existing.place_type,
            place_id=patch.place_id if patch.place_id is not None else existing.place_id,
            metadata=patch.metadata if patch.metadata is not None else existing.metadata,
            manually_edited=True,
            address=patch.address if patch.address is not None else existing.address,
            image_urls=(
                list(patch.image_urls) if patch.image_urls is not None else existing.image_urls
            ),
            reviews=(
                patch.reviews
                if patch.reviews is not None
                else (None if patch.clear_reviews else existing.reviews)
            ),
            created_at=existing.created_at,
            updated_at=existing.updated_at,
        )

        persisted = await self.property_poi_repo.update(updated)
        await self.property_repo.bump_aggregate_version(property_id)
        return persisted
