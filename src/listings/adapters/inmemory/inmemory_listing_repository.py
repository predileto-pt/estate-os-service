from uuid import UUID

from listings.application.ports.listing_repository import ListingRepository, PropertyFilters
from listings.domain.models import ListedProperty


class InMemoryListingRepository(ListingRepository):
    def __init__(self) -> None:
        self._properties: dict[UUID, ListedProperty] = {}

    def add(self, prop: ListedProperty) -> None:
        self._properties[prop.id] = prop

    async def list_active(self, filters: PropertyFilters) -> list[ListedProperty]:
        results = list(self._properties.values())

        if filters.listing_type is not None:
            results = [p for p in results if p.listing_type == filters.listing_type]
        if filters.typology is not None:
            results = [p for p in results if p.typology == filters.typology]
        if filters.district is not None:
            results = [p for p in results if filters.district.lower() in p.address.lower()]
        if filters.min_price is not None:
            results = [p for p in results if p.prices and p.prices[0].amount >= filters.min_price]
        if filters.max_price is not None:
            results = [p for p in results if p.prices and p.prices[0].amount <= filters.max_price]

        results.sort(key=lambda p: p.created_at, reverse=True)
        return results[filters.offset : filters.offset + filters.limit]

    async def get_by_id(self, property_id: UUID) -> ListedProperty | None:
        return self._properties.get(property_id)

    async def count_active(self, filters: PropertyFilters) -> int:
        results = await self.list_active(PropertyFilters(
            listing_type=filters.listing_type,
            typology=filters.typology,
            min_price=filters.min_price,
            max_price=filters.max_price,
            district=filters.district,
            limit=999999,
            offset=0,
        ))
        return len(results)
