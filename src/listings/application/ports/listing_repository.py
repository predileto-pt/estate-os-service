from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from listings.domain.models import ListedProperty, ListingType, Typology


@dataclass
class PropertyFilters:
    listing_type: ListingType | None = None
    typology: Typology | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    district: str | None = None
    limit: int = 50
    offset: int = 0


class ListingRepository(ABC):
    @abstractmethod
    async def list_active(self, filters: PropertyFilters) -> list[ListedProperty]: ...

    @abstractmethod
    async def get_by_id(self, property_id: UUID) -> ListedProperty | None: ...

    @abstractmethod
    async def count_active(self, filters: PropertyFilters) -> int: ...
