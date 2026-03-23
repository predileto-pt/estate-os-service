from __future__ import annotations

from uuid import UUID

from supabase import AsyncClient

from property_management.application.ports.repositories.property_amenity_repository import (
    PropertyAmenityRepository,
)
from property_management.domain.models.property_amenity import (
    AmenityCategory,
    NearbyPlace,
    PropertyAmenity,
)


class SupabasePropertyAmenityRepository(PropertyAmenityRepository):
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    @staticmethod
    def _to_domain(row: dict) -> PropertyAmenity:
        return PropertyAmenity(
            id=UUID(row["id"]),
            property_id=UUID(row["property_id"]),
            category=AmenityCategory(row["category"]),
            nearest_name=row["nearest_name"],
            nearest_distance_meters=row["nearest_distance_meters"],
            nearest_latitude=row["nearest_latitude"],
            nearest_longitude=row["nearest_longitude"],
            total_count=row["total_count"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            nearest_place_id=row.get("nearest_place_id"),
            nearest_google_maps_url=row.get("nearest_google_maps_url"),
            top_places=[NearbyPlace.from_dict(p) for p in (row.get("top_places") or [])],
        )

    @staticmethod
    def _to_row(amenity: PropertyAmenity) -> dict:
        return {
            "id": str(amenity.id),
            "property_id": str(amenity.property_id),
            "category": amenity.category.value,
            "nearest_name": amenity.nearest_name,
            "nearest_distance_meters": amenity.nearest_distance_meters,
            "nearest_latitude": amenity.nearest_latitude,
            "nearest_longitude": amenity.nearest_longitude,
            "total_count": amenity.total_count,
            "nearest_place_id": amenity.nearest_place_id,
            "nearest_google_maps_url": amenity.nearest_google_maps_url,
            "top_places": [p.to_dict() for p in amenity.top_places],
        }

    async def save_batch(self, amenities: list[PropertyAmenity]) -> list[PropertyAmenity]:
        rows = [self._to_row(a) for a in amenities]
        result = await self._client.table("property_amenities").insert(rows).execute()
        return [self._to_domain(r) for r in result.data]

    async def get_by_property_id(self, property_id: UUID) -> list[PropertyAmenity]:
        result = (
            await self._client.table("property_amenities")
            .select("*")
            .eq("property_id", str(property_id))
            .order("category", desc=False)
            .execute()
        )
        return [self._to_domain(r) for r in result.data]

    async def delete_by_property_id(self, property_id: UUID) -> None:
        await (
            self._client.table("property_amenities")
            .delete()
            .eq("property_id", str(property_id))
            .execute()
        )
