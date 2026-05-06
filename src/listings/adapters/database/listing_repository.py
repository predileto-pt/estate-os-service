from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select

from listings.adapters.database.models import (
    PropertyStatus,
    ReadPropertyImageModel,
    ReadPropertyModel,
    ReadPropertyPriceModel,
)
from listings.application.ports.listing_repository import (
    ListingRepository,
    PropertyFilters,
)
from listings.domain.models import (
    ListedProperty,
    ListingType,
    PropertyCharacteristics,
    PropertyImage,
    PropertyPrice,
    Typology,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class SqlAlchemyListingRepository(ListingRepository):
    """One fresh `AsyncSession` per public method call. See the analogous
    docstring on `SqlAlchemyPropertyListingRepository`."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_active(self, filters: PropertyFilters) -> list[ListedProperty]:
        async with self._session_factory() as session:
            query = self._build_query(filters)
            query = query.order_by(ReadPropertyModel.created_at.desc())
            query = query.limit(filters.limit).offset(filters.offset)

            result = await session.execute(query)
            properties = []
            for row in result.scalars().all():
                prices = await self._load_prices(session, row.id)
                images = await self._load_images(session, row.id)

                if filters.min_price is not None or filters.max_price is not None:
                    if not self._matches_price_filter(prices, filters.min_price, filters.max_price):
                        continue

                properties.append(self._to_domain(row, prices, images))
            return properties

    async def get_by_id(self, property_id: UUID) -> ListedProperty | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ReadPropertyModel).where(
                    ReadPropertyModel.id == str(property_id),
                    ReadPropertyModel.status == PropertyStatus.ACTIVE,
                )
            )
            row = result.scalar_one_or_none()
            if not row:
                return None
            prices = await self._load_prices(session, row.id)
            images = await self._load_images(session, row.id)
            return self._to_domain(row, prices, images)

    async def count_active(self, filters: PropertyFilters) -> int:
        async with self._session_factory() as session:
            query = self._build_query(filters)
            count_query = select(func.count()).select_from(query.subquery())
            result = await session.execute(count_query)
            return result.scalar_one()

    async def list_active_for_organization(
        self, organization_id: UUID, filters: PropertyFilters
    ) -> list[ListedProperty]:
        """Return ACTIVE listings for one organization. The `WHERE status = ACTIVE`
        predicate comes from `_build_query` and is the canonical enforcement of
        status filtering — the in-memory adapter does NOT honor this
        (`ListedProperty` carries no `status` field) and is unsuitable for
        status-exclusion testing.
        """
        async with self._session_factory() as session:
            query = self._build_query(filters)
            query = query.where(ReadPropertyModel.organization_id == str(organization_id))
            query = query.order_by(ReadPropertyModel.updated_at.desc())
            query = query.limit(filters.limit).offset(filters.offset)

            result = await session.execute(query)
            properties = []
            for row in result.scalars().all():
                prices = await self._load_prices(session, row.id)
                images = await self._load_images(session, row.id)

                if filters.min_price is not None or filters.max_price is not None:
                    if not self._matches_price_filter(prices, filters.min_price, filters.max_price):
                        continue

                properties.append(self._to_domain(row, prices, images))
            return properties

    async def count_active_for_organization(
        self, organization_id: UUID, filters: PropertyFilters
    ) -> int:
        async with self._session_factory() as session:
            query = self._build_query(filters)
            query = query.where(ReadPropertyModel.organization_id == str(organization_id))
            count_query = select(func.count()).select_from(query.subquery())
            result = await session.execute(count_query)
            return result.scalar_one()

    def _build_query(self, filters: PropertyFilters):
        query = select(ReadPropertyModel).where(ReadPropertyModel.status == PropertyStatus.ACTIVE)

        if filters.listing_type is not None:
            query = query.where(ReadPropertyModel.listing_type == filters.listing_type.value)
        if filters.typology is not None:
            query = query.where(ReadPropertyModel.typology == filters.typology.value)
        if filters.district is not None:
            query = query.where(ReadPropertyModel.address.ilike(f"%{filters.district}%"))

        return query

    @staticmethod
    def _matches_price_filter(
        prices: list[ReadPropertyPriceModel],
        min_price: Decimal | None,
        max_price: Decimal | None,
    ) -> bool:
        if not prices:
            return False
        latest_price = Decimal(str(prices[0].amount))
        if min_price is not None and latest_price < min_price:
            return False
        if max_price is not None and latest_price > max_price:
            return False
        return True

    async def _load_prices(
        self, session: AsyncSession, property_id: str
    ) -> list[ReadPropertyPriceModel]:
        result = await session.execute(
            select(ReadPropertyPriceModel)
            .where(ReadPropertyPriceModel.property_id == property_id)
            .order_by(ReadPropertyPriceModel.created_at.desc())
        )
        return list(result.scalars().all())

    async def _load_images(
        self, session: AsyncSession, property_id: str
    ) -> list[ReadPropertyImageModel]:
        result = await session.execute(
            select(ReadPropertyImageModel)
            .where(ReadPropertyImageModel.property_id == property_id)
            .order_by(ReadPropertyImageModel.display_order.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    def _to_domain(
        m: ReadPropertyModel,
        prices: list[ReadPropertyPriceModel],
        images: list[ReadPropertyImageModel],
    ) -> ListedProperty:
        return ListedProperty(
            id=UUID(m.id),
            organization_id=UUID(m.organization_id),
            address=m.address,
            listing_type=ListingType(m.listing_type.value),
            typology=Typology(m.typology.value),
            description=m.description,
            characteristics=(
                PropertyCharacteristics.from_dict(m.characteristics) if m.characteristics else None
            ),
            latitude=m.latitude,
            longitude=m.longitude,
            created_at=m.created_at,
            updated_at=m.updated_at,
            prices=[
                PropertyPrice(
                    id=UUID(p.id),
                    property_id=UUID(p.property_id),
                    amount=Decimal(str(p.amount)),
                    listing_type=ListingType(
                        p.listing_type.value if hasattr(p.listing_type, "value") else p.listing_type
                    ),
                    created_at=p.created_at,
                    updated_at=p.updated_at,
                )
                for p in prices
            ],
            images=[
                PropertyImage(
                    id=UUID(i.id),
                    property_id=UUID(i.property_id),
                    s3_key=i.s3_key,
                    filename=i.filename,
                    content_type=i.content_type,
                    size_bytes=i.size_bytes,
                    display_order=i.display_order,
                    created_at=i.created_at,
                    updated_at=i.updated_at,
                )
                for i in images
            ],
        )
