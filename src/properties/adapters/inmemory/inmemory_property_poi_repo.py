from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from properties.application.ports.repositories.property_poi_repository import (
    PropertyPoiRepository,
)
from properties.domain.models.property_poi import PropertyPoi


class InMemoryPropertyPoiRepository(PropertyPoiRepository):
    def __init__(self) -> None:
        self._pois: dict[UUID, PropertyPoi] = {}

    async def list_by_property(self, property_id: UUID) -> list[PropertyPoi]:
        results = [p for p in self._pois.values() if p.property_id == property_id]
        # Newest first — matches the SQL adapter's ORDER BY created_at DESC.
        results.sort(key=lambda p: p.created_at or datetime.min, reverse=True)
        return results

    async def get_by_id(self, poi_id: UUID) -> PropertyPoi | None:
        return self._pois.get(poi_id)

    async def replace_for_property(
        self, *, property_id: UUID, pois: list[PropertyPoi]
    ) -> list[PropertyPoi]:
        existing_ids = [pid for pid, p in self._pois.items() if p.property_id == property_id]
        for pid in existing_ids:
            del self._pois[pid]

        now = datetime.now(timezone.utc)
        persisted: list[PropertyPoi] = []
        for poi in pois:
            new_id = poi.id if poi.id else uuid4()
            new_poi = PropertyPoi(
                id=new_id,
                property_id=property_id,
                category=poi.category,
                name=poi.name,
                distance_meters=poi.distance_meters,
                latitude=poi.latitude,
                longitude=poi.longitude,
                place_type=poi.place_type,
                place_id=poi.place_id,
                metadata=dict(poi.metadata),
                manually_edited=poi.manually_edited,
                created_at=now,
                updated_at=now,
            )
            self._pois[new_id] = new_poi
            persisted.append(new_poi)
        return persisted

    async def update(self, poi: PropertyPoi) -> PropertyPoi:
        existing = self._pois.get(poi.id)
        if existing is None:
            from properties.domain.exceptions import PropertyNotFoundError

            raise PropertyNotFoundError(str(poi.id))

        updated = PropertyPoi(
            id=poi.id,
            property_id=poi.property_id,
            category=poi.category,
            name=poi.name,
            distance_meters=poi.distance_meters,
            latitude=poi.latitude,
            longitude=poi.longitude,
            place_type=poi.place_type,
            place_id=poi.place_id,
            metadata=dict(poi.metadata),
            manually_edited=poi.manually_edited,
            created_at=existing.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        self._pois[poi.id] = updated
        return updated

    async def delete(self, poi_id: UUID) -> bool:
        if poi_id in self._pois:
            del self._pois[poi_id]
            return True
        return False
