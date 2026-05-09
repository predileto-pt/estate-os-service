from __future__ import annotations

from datetime import datetime
from uuid import UUID

import structlog
from supabase import AsyncClient

from properties.application.ports.repositories.property_poi_repository import (
    PropertyPoiRepository,
)
from properties.domain.models.property_poi import PoiCategory, PropertyPoi

log = structlog.get_logger()


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class SupabasePropertyPoiRepository(PropertyPoiRepository):
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    @staticmethod
    def _to_domain(row: dict) -> PropertyPoi:
        return PropertyPoi(
            id=UUID(row["id"]),
            property_id=UUID(row["property_id"]),
            category=PoiCategory(row["category"]),
            name=row["name"],
            distance_meters=row["distance_meters"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            place_type=row.get("place_type"),
            place_id=row.get("place_id"),
            metadata=row.get("metadata") or {},
            manually_edited=row.get("manually_edited", False),
            address=row.get("address"),
            image_urls=row.get("image_urls") or [],
            reviews=row.get("reviews"),
            created_at=_parse_datetime(row.get("created_at")),
            updated_at=_parse_datetime(row.get("updated_at")),
        )

    @staticmethod
    def _to_row(poi: PropertyPoi) -> dict:
        # Skip id/timestamps so the DB defaults populate them on insert.
        return {
            "property_id": str(poi.property_id),
            "category": poi.category.value,
            "name": poi.name,
            "distance_meters": poi.distance_meters,
            "latitude": poi.latitude,
            "longitude": poi.longitude,
            "place_type": poi.place_type,
            "place_id": poi.place_id,
            "metadata": poi.metadata,
            "manually_edited": poi.manually_edited,
            "address": poi.address,
            "image_urls": poi.image_urls,
            "reviews": poi.reviews,
        }

    async def list_by_property(self, property_id: UUID) -> list[PropertyPoi]:
        result = (
            await self._client.table("property_pois")
            .select("*")
            .eq("property_id", str(property_id))
            .order("created_at", desc=True)
            .execute()
        )
        return [self._to_domain(r) for r in result.data]

    async def get_by_id(self, poi_id: UUID) -> PropertyPoi | None:
        result = (
            await self._client.table("property_pois")
            .select("*")
            .eq("id", str(poi_id))
            .limit(1)
            .execute()
        )
        rows = result.data
        if not rows:
            return None
        return self._to_domain(rows[0])

    async def replace_for_property(
        self, *, property_id: UUID, pois: list[PropertyPoi]
    ) -> list[PropertyPoi]:
        # Two-step delete-then-insert. PostgREST has no transactional
        # batch primitive; the small race window where the property has
        # zero POIs is acceptable for an interactive agent action.
        delete_result = await (
            self._client.table("property_pois")
            .delete()
            .eq("property_id", str(property_id))
            .execute()
        )
        log.info(
            "property_poi_repo.delete_existing",
            property_id=str(property_id),
            deleted_count=len(delete_result.data) if delete_result.data else 0,
        )

        if not pois:
            return []

        rows = [self._to_row(p) for p in pois]
        result = await self._client.table("property_pois").insert(rows).execute()
        persisted = result.data or []
        # Defense against silent failures (RLS, constraint violations,
        # PostgREST swallowing errors). PostgREST returns 0 rows when
        # RLS filters the new rows out; the client doesn't raise on
        # this. We refuse to silently lie to the caller about success.
        if len(persisted) != len(rows):
            raise RuntimeError(
                f"property_pois insert: attempted {len(rows)}, persisted "
                f"{len(persisted)} for property_id={property_id}. "
                "Possible causes: RLS policy denying writes, FK violation, "
                "or PostgREST swallowing an error."
            )
        log.info(
            "property_poi_repo.insert_complete",
            property_id=str(property_id),
            attempted=len(rows),
            persisted=len(persisted),
        )
        return [self._to_domain(r) for r in persisted]

    async def update(self, poi: PropertyPoi) -> PropertyPoi:
        result = (
            await self._client.table("property_pois")
            .update(self._to_row(poi))
            .eq("id", str(poi.id))
            .execute()
        )
        rows = result.data
        if not rows:
            from properties.domain.exceptions import PropertyNotFoundError

            raise PropertyNotFoundError(str(poi.id))
        return self._to_domain(rows[0])

    async def update_place_details(
        self,
        *,
        poi_id: UUID,
        address: str | None,
        image_urls: list[str],
        reviews: list[dict] | None,
    ) -> None:
        # Touch only the place-details columns (spec
        # 2026-05-poi-rich-metadata §Repository). Other columns are
        # untouched, so Phase 1's ranking-time data is safe.
        await (
            self._client.table("property_pois")
            .update(
                {
                    "address": address,
                    "image_urls": image_urls,
                    "reviews": reviews,
                }
            )
            .eq("id", str(poi_id))
            .execute()
        )

    async def delete(self, poi_id: UUID) -> bool:
        result = await self._client.table("property_pois").delete().eq("id", str(poi_id)).execute()
        return bool(result.data)
