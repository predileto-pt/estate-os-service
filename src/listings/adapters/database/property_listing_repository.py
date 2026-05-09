"""SQLAlchemy adapter for `PropertyListingRepository`.

`upsert_from_event` uses PostgreSQL's ON CONFLICT ... DO UPDATE with a
WHERE clause on `source_aggregate_version` — so replayed or out-of-order
events with a stale version are silently dropped. Same guard on
`delete_if_newer`.

The projector calls this from the listings worker; the enrichment
handler calls `update_location` / `increment_enrichment_attempts`.

**Session scope:** one fresh `AsyncSession` per public method call. The
listings worker handles many events in sequence on the same process, and
sharing a single long-lived session across handlers leaks state and
triggers `MissingGreenlet` errors when ORM objects loaded in one
operation are accessed under a different async/greenlet context. The
repo therefore owns the session lifecycle entirely — every method opens
a session, commits on success, rolls back on exception, and closes.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from listings.adapters.database.property_listing_model import PropertyListingModel
from listings.application.ports.address_searcher import ParsedAddress
from listings.application.ports.repositories.property_listing_repository import (
    PropertyListingRepository,
)
from listings.domain.models import ListingType, PropertyStatus, Typology
from listings.domain.property_filters import PropertyFilters
from listings.domain.property_listing import (
    ListingImage,
    ListingPoi,
    ListingPrice,
    PropertyListing,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class SqlAlchemyPropertyListingRepository(PropertyListingRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _to_domain(m: PropertyListingModel) -> PropertyListing:
        pois_raw = m.pois or []
        return PropertyListing(
            id=UUID(m.id),
            organization_id=UUID(m.organization_id),
            status=PropertyStatus(m.status.value if hasattr(m.status, "value") else m.status),
            listing_type=ListingType(
                m.listing_type.value if hasattr(m.listing_type, "value") else m.listing_type
            ),
            typology=Typology(m.typology.value if hasattr(m.typology, "value") else m.typology),
            parish=m.parish,
            municipality=m.municipality,
            district=m.district,
            location_enriched_at=m.location_enriched_at,
            location_enrichment_attempts=m.location_enrichment_attempts,
            num_of_bedrooms=m.num_of_bedrooms,
            num_of_bathrooms=m.num_of_bathrooms,
            area_in_m2=m.area_in_m2,
            has_pool=m.has_pool,
            has_garden=m.has_garden,
            has_elevator=m.has_elevator,
            floor=m.floor,
            parking_spaces=m.parking_spaces,
            built_at=m.built_at,
            energy_rating=m.energy_rating,
            country=m.country,
            city=m.city,
            state=m.state,
            region=m.region,
            min_price=m.min_price,
            first_image_s3_key=m.first_image_s3_key,
            images=[
                ListingImage(
                    id=UUID(img["id"]),
                    s3_key=img["s3_key"],
                    display_order=int(img["display_order"]),
                )
                for img in (m.images or [])
            ],
            prices=[
                ListingPrice(
                    amount=Decimal(str(p["amount"])),
                    listing_type=ListingType(p["listing_type"]),
                )
                for p in (m.prices or [])
            ],
            description=m.description,
            latitude=m.latitude,
            longitude=m.longitude,
            source_aggregate_version=m.source_aggregate_version,
            source_occurred_at=m.source_occurred_at,
            created_at=m.created_at,
            updated_at=m.updated_at,
            pois=[
                ListingPoi(
                    category=p["category"],
                    name=p["name"],
                    distance_meters=float(p["distance_meters"]),
                )
                for p in pois_raw
            ],
            embedding_text_hash=m.embedding_text_hash,
            canonical_text_version=m.canonical_text_version,
            embedding_model_version=m.embedding_model_version,
            embedded_at=m.embedded_at,
            embedding_status=m.embedding_status,
        )

    async def get_by_id(self, property_id: UUID) -> PropertyListing | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(PropertyListingModel).where(PropertyListingModel.id == str(property_id))
            )
            row = result.scalar_one_or_none()
            return self._to_domain(row) if row else None

    # ──────────── Read side (public + admin route handlers) ────────────

    def _build_active_query(self, filters: PropertyFilters):
        from listings.domain.models import PropertyStatus as _PStatus

        query = select(PropertyListingModel).where(PropertyListingModel.status == _PStatus.ACTIVE)
        if filters.listing_type is not None:
            query = query.where(PropertyListingModel.listing_type == filters.listing_type.value)
        if filters.typology is not None:
            query = query.where(PropertyListingModel.typology == filters.typology.value)
        if filters.parish is not None:
            query = query.where(PropertyListingModel.parish == filters.parish)
        if filters.municipality is not None:
            query = query.where(PropertyListingModel.municipality == filters.municipality)
        if filters.district is not None:
            query = query.where(PropertyListingModel.district == filters.district)
        if filters.min_price is not None:
            query = query.where(PropertyListingModel.min_price >= filters.min_price)
        if filters.max_price is not None:
            query = query.where(PropertyListingModel.min_price <= filters.max_price)
        return query

    async def list_active(self, filters: PropertyFilters) -> list[PropertyListing]:
        async with self._session_factory() as session:
            query = (
                self._build_active_query(filters)
                .order_by(
                    PropertyListingModel.created_at.desc(),
                    PropertyListingModel.id.desc(),
                )
                .limit(filters.limit)
                .offset(filters.offset)
            )
            result = await session.execute(query)
            return [self._to_domain(row) for row in result.scalars().all()]

    async def count_active(self, filters: PropertyFilters) -> int:
        async with self._session_factory() as session:
            count_query = select(func.count()).select_from(
                self._build_active_query(filters).subquery()
            )
            result = await session.execute(count_query)
            return result.scalar_one()

    async def list_active_for_organization(
        self, organization_id: UUID, filters: PropertyFilters
    ) -> list[PropertyListing]:
        async with self._session_factory() as session:
            query = (
                self._build_active_query(filters)
                .where(PropertyListingModel.organization_id == str(organization_id))
                .order_by(
                    PropertyListingModel.created_at.desc(),
                    PropertyListingModel.id.desc(),
                )
                .limit(filters.limit)
                .offset(filters.offset)
            )
            result = await session.execute(query)
            return [self._to_domain(row) for row in result.scalars().all()]

    async def count_active_for_organization(
        self, organization_id: UUID, filters: PropertyFilters
    ) -> int:
        async with self._session_factory() as session:
            query = self._build_active_query(filters).where(
                PropertyListingModel.organization_id == str(organization_id)
            )
            count_query = select(func.count()).select_from(query.subquery())
            result = await session.execute(count_query)
            return result.scalar_one()

    # ──────────── Write side (listings worker handlers) ───────────────

    async def upsert_from_event(
        self,
        *,
        event_data: dict,
        source_occurred_at: datetime,
    ) -> PropertyListing | None:
        row = _event_to_row(event_data, source_occurred_at)
        async with self._session_factory() as session:
            stmt = pg_insert(PropertyListingModel).values(**row)
            # Three groups of columns are owned by *other* handlers, not
            # the projector, so they must NOT be in the UPDATE SET
            # clause (they'd silently regress on every PROPERTY_UPDATED):
            #
            # - location columns (parish/municipality/district +
            #   location_enriched_at + location_enrichment_attempts) are
            #   written by `handle_address_enrichment` after the LLM
            #   parses the free-text address. The InMemory adapter
            #   already preserves these; the SqlAlchemy adapter was
            #   wiping them on every update.
            # - embedding columns are written by the embedding handler.
            stmt = stmt.on_conflict_do_update(
                index_elements=["id"],
                set_={
                    k: stmt.excluded[k]
                    for k in row
                    if k
                    not in (
                        "id",
                        "created_at",
                        # Location columns owned by the enrichment handler;
                        # the projector must not regress them on UPDATE.
                        "parish",
                        "municipality",
                        "district",
                        "country",
                        "city",
                        "state",
                        "region",
                        "location_enriched_at",
                        "location_enrichment_attempts",
                        "embedding_text_hash",
                        "canonical_text_version",
                        "embedding_model_version",
                        "embedded_at",
                        "embedding_status",
                    )
                }
                | {"updated_at": func.now()},
                where=PropertyListingModel.source_aggregate_version
                < stmt.excluded.source_aggregate_version,
            )
            await session.execute(stmt)
            await session.commit()

            # Re-fetch in the same session so attribute reads in `_to_domain`
            # don't trigger refresh against a closed connection.
            refetch = await session.execute(
                select(PropertyListingModel).where(PropertyListingModel.id == row["id"])
            )
            model = refetch.scalar_one_or_none()
            return self._to_domain(model) if model else None

    async def delete_if_newer(
        self,
        *,
        property_id: UUID,
        source_aggregate_version: int,
        source_occurred_at: datetime,
    ) -> bool:
        async with self._session_factory() as session:
            existing = await session.execute(
                select(PropertyListingModel).where(PropertyListingModel.id == str(property_id))
            )
            existing_model = existing.scalar_one_or_none()
            if existing_model is None:
                return False
            if existing_model.source_aggregate_version >= source_aggregate_version:
                return False

            from sqlalchemy import delete as sql_delete

            await session.execute(
                sql_delete(PropertyListingModel).where(PropertyListingModel.id == str(property_id))
            )
            await session.commit()
            return True

    async def update_location(
        self,
        *,
        property_id: UUID,
        parsed: ParsedAddress,
    ) -> PropertyListing | None:
        """Persist the universal `ParsedAddress` envelope returned by the
        country-specific `AddressSearcher` — every per-country
        implementation fills its country's fields and leaves the others
        None. We write all of them; nullable columns absorb the Nones.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(PropertyListingModel).where(PropertyListingModel.id == str(property_id))
            )
            model = result.scalar_one_or_none()
            if model is None:
                return None
            model.parish = parsed.parish
            model.municipality = parsed.municipality
            model.district = parsed.district
            model.country = parsed.country
            model.city = parsed.city
            model.state = parsed.state
            model.region = parsed.region
            model.location_enriched_at = func.now()
            model.location_enrichment_attempts = (model.location_enrichment_attempts or 0) + 1
            await session.commit()

            # Refresh inside the session so the domain mapping below stays
            # within an active connection scope.
            await session.refresh(model)
            return self._to_domain(model)

    async def increment_enrichment_attempts(self, *, property_id: UUID) -> PropertyListing | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(PropertyListingModel).where(PropertyListingModel.id == str(property_id))
            )
            model = result.scalar_one_or_none()
            if model is None:
                return None
            model.location_enrichment_attempts = (model.location_enrichment_attempts or 0) + 1
            await session.commit()
            await session.refresh(model)
            return self._to_domain(model)

    async def set_embedding_indexed(
        self,
        *,
        property_id: UUID,
        embedding_text_hash: str,
        canonical_text_version: str,
        embedding_model_version: str,
        embedded_at: datetime,
    ) -> PropertyListing | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(PropertyListingModel).where(PropertyListingModel.id == str(property_id))
            )
            model = result.scalar_one_or_none()
            if model is None:
                return None
            model.embedding_text_hash = embedding_text_hash
            model.canonical_text_version = canonical_text_version
            model.embedding_model_version = embedding_model_version
            model.embedded_at = embedded_at
            model.embedding_status = "INDEXED"
            await session.commit()
            await session.refresh(model)
            return self._to_domain(model)

    async def set_embedding_status(
        self, *, property_id: UUID, status: str
    ) -> PropertyListing | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(PropertyListingModel).where(PropertyListingModel.id == str(property_id))
            )
            model = result.scalar_one_or_none()
            if model is None:
                return None
            model.embedding_status = status
            await session.commit()
            await session.refresh(model)
            return self._to_domain(model)


def _event_to_row(data: dict, source_occurred_at: datetime) -> dict:
    """Map a carried-state event payload to a `property_listings` row dict.

    Chooses the minimum `amount` across `data["prices"]` as `min_price`
    (matching the filter intent of the read API). Picks the image with
    `display_order == 0` as `first_image_s3_key`, falling back to the
    first in the list.
    """
    prices = data.get("prices") or []
    min_price: Decimal | None = None
    for p in prices:
        try:
            amt = Decimal(str(p["amount"]))
        except (InvalidOperation, KeyError, TypeError):
            continue
        if min_price is None or amt < min_price:
            min_price = amt

    images = data.get("images") or []
    first_image = None
    for img in images:
        if img.get("display_order") == 0:
            first_image = img.get("s3_key")
            break
    if first_image is None and images:
        first_image = images[0].get("s3_key")

    chars = data.get("characteristics") or {}

    row = {
        "id": data["id"],
        "organization_id": data["organization_id"],
        "status": data["status"],
        "listing_type": data["listing_type"],
        "typology": data["typology"],
        # `address` is no longer a column on this table — see spec
        # 2026-05-property-address-enrichment-fix. The projector reads
        # `data["address"]` to forward to the enrichment event but does
        # not write it to the row.
        "parish": None,
        "municipality": None,
        "district": None,
        "country": data.get("country") or "Portugal",
        "city": None,
        "state": None,
        "region": None,
        "location_enriched_at": None,
        "location_enrichment_attempts": 0,
        "num_of_bedrooms": chars.get("num_of_bedrooms"),
        "num_of_bathrooms": chars.get("num_of_bathrooms"),
        "area_in_m2": (int(chars["area_in_m2"]) if chars.get("area_in_m2") is not None else None),
        "has_pool": chars.get("has_pool"),
        "has_garden": chars.get("has_garden"),
        "has_elevator": chars.get("has_elevator"),
        "floor": chars.get("floor"),
        "parking_spaces": chars.get("parking_spaces"),
        "built_at": chars.get("built_at"),
        "energy_rating": chars.get("energy_rating"),
        "min_price": min_price,
        "first_image_s3_key": first_image,
        # Full image + price lists projected from the snapshot. Lean
        # shape — only the fields the public response renders. Snapshot
        # already carries the right shape; we just write it through.
        "images": images,
        "prices": [
            {
                "amount": p["amount"],
                "listing_type": p["listing_type"],
            }
            for p in prices
            if "amount" in p and "listing_type" in p
        ],
        "description": data.get("description"),
        "latitude": data.get("latitude"),
        "longitude": data.get("longitude"),
        "source_aggregate_version": data["aggregate_version"],
        "source_occurred_at": source_occurred_at,
    }

    # POIs: snapshot key presence is meaningful. When the snapshot
    # carries `pois` (even `[]`), it's authoritative — write it. When the
    # key is absent, the emitter wasn't publishing POI state — preserve
    # whatever's already on the row by omitting it from the row dict
    # (the upsert SET clause skips columns not in the dict).
    if "pois" in data:
        row["pois"] = data["pois"] or []

    return row
