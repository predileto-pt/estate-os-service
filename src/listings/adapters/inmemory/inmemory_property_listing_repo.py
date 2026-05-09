"""In-memory `PropertyListingRepository` for tests.

Same idempotency semantics as the SQLAlchemy adapter:
`upsert_from_event` drops the write when the incoming
`source_aggregate_version` is <= the stored value; `delete_if_newer`
drops the delete when the incoming version is <= stored.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID

from listings.application.ports.repositories.property_listing_repository import (
    PropertyListingRepository,
)
from listings.domain.models import ListingType, PropertyStatus, Typology
from listings.domain.property_listing import ListingPoi, PropertyListing


class InMemoryPropertyListingRepository(PropertyListingRepository):
    def __init__(self) -> None:
        self._rows: dict[UUID, PropertyListing] = {}

    async def get_by_id(self, property_id: UUID) -> PropertyListing | None:
        return self._rows.get(property_id)

    async def upsert_from_event(
        self,
        *,
        event_data: dict,
        source_occurred_at: datetime,
    ) -> PropertyListing | None:
        property_id = UUID(event_data["id"])
        incoming_version: int = event_data["aggregate_version"]
        existing = self._rows.get(property_id)
        if existing is not None and existing.source_aggregate_version >= incoming_version:
            return None  # idempotency guard — drop older/equal event

        now = datetime.now(timezone.utc)
        chars = event_data.get("characteristics") or {}
        prices = event_data.get("prices") or []
        min_price: Decimal | None = None
        for p in prices:
            try:
                amt = Decimal(str(p["amount"]))
            except (InvalidOperation, KeyError, TypeError):
                continue
            if min_price is None or amt < min_price:
                min_price = amt

        images = event_data.get("images") or []
        first_image = None
        for img in images:
            if img.get("display_order") == 0:
                first_image = img.get("s3_key")
                break
        if first_image is None and images:
            first_image = images[0].get("s3_key")

        # POIs: when the snapshot carries `pois` it's authoritative; when
        # absent, preserve whatever's on the existing row.
        if "pois" in event_data:
            pois = [
                ListingPoi(
                    category=p["category"],
                    name=p["name"],
                    distance_meters=float(p["distance_meters"]),
                )
                for p in (event_data.get("pois") or [])
            ]
        else:
            pois = list(existing.pois) if existing else []

        listing = PropertyListing(
            id=property_id,
            organization_id=UUID(event_data["organization_id"]),
            status=PropertyStatus(event_data["status"]),
            listing_type=ListingType(event_data["listing_type"]),
            typology=Typology(event_data["typology"]),
            address=event_data["address"],
            parish=existing.parish if existing else None,
            municipality=existing.municipality if existing else None,
            district=existing.district if existing else None,
            location_enriched_at=existing.location_enriched_at if existing else None,
            location_enrichment_attempts=(existing.location_enrichment_attempts if existing else 0),
            num_of_bedrooms=chars.get("num_of_bedrooms"),
            num_of_bathrooms=chars.get("num_of_bathrooms"),
            area_in_m2=(int(chars["area_in_m2"]) if chars.get("area_in_m2") is not None else None),
            has_pool=chars.get("has_pool"),
            has_garden=chars.get("has_garden"),
            has_elevator=chars.get("has_elevator"),
            built_at=chars.get("built_at"),
            energy_rating=chars.get("energy_rating"),
            min_price=min_price,
            first_image_s3_key=first_image,
            description=event_data.get("description"),
            latitude=event_data.get("latitude"),
            longitude=event_data.get("longitude"),
            source_aggregate_version=incoming_version,
            source_occurred_at=source_occurred_at,
            created_at=existing.created_at if existing else now,
            updated_at=now,
            pois=pois,
            # Embedding columns are owned by the embedding handler — preserve
            # what's there (initial value for fresh row, untouched on update).
            embedding_text_hash=existing.embedding_text_hash if existing else None,
            canonical_text_version=existing.canonical_text_version if existing else None,
            embedding_model_version=existing.embedding_model_version if existing else None,
            embedded_at=existing.embedded_at if existing else None,
            embedding_status=existing.embedding_status if existing else "PENDING",
        )
        self._rows[property_id] = listing
        return listing

    async def delete_if_newer(
        self,
        *,
        property_id: UUID,
        source_aggregate_version: int,
        source_occurred_at: datetime,
    ) -> bool:
        existing = self._rows.get(property_id)
        if existing is None:
            return False
        if existing.source_aggregate_version >= source_aggregate_version:
            return False
        del self._rows[property_id]
        return True

    async def update_location(
        self,
        *,
        property_id: UUID,
        parish: str | None,
        municipality: str | None,
        district: str | None,
    ) -> PropertyListing | None:
        existing = self._rows.get(property_id)
        if existing is None:
            return None
        existing.parish = parish
        existing.municipality = municipality
        existing.district = district
        existing.location_enriched_at = datetime.now(timezone.utc)
        existing.location_enrichment_attempts += 1
        return existing

    async def increment_enrichment_attempts(self, *, property_id: UUID) -> PropertyListing | None:
        existing = self._rows.get(property_id)
        if existing is None:
            return None
        existing.location_enrichment_attempts += 1
        return existing

    async def set_embedding_indexed(
        self,
        *,
        property_id: UUID,
        embedding_text_hash: str,
        canonical_text_version: str,
        embedding_model_version: str,
        embedded_at: datetime,
    ) -> PropertyListing | None:
        existing = self._rows.get(property_id)
        if existing is None:
            return None
        existing.embedding_text_hash = embedding_text_hash
        existing.canonical_text_version = canonical_text_version
        existing.embedding_model_version = embedding_model_version
        existing.embedded_at = embedded_at
        existing.embedding_status = "INDEXED"
        return existing

    async def set_embedding_status(
        self, *, property_id: UUID, status: str
    ) -> PropertyListing | None:
        existing = self._rows.get(property_id)
        if existing is None:
            return None
        existing.embedding_status = status
        return existing
