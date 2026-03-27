from abc import ABC, abstractmethod
from uuid import UUID

from property_management.domain.models.property import Property
from property_management.domain.models.property_image import PropertyImage
from property_management.domain.models.property_owner import PropertyOwner
from property_management.domain.models.property_price import PropertyPrice


class PropertyRepository(ABC):
    @abstractmethod
    async def get_by_id(self, property_id: UUID) -> Property | None: ...

    @abstractmethod
    async def list_by_organization(self, organization_id: UUID) -> list[Property]: ...

    @abstractmethod
    async def save(self, prop: Property) -> Property: ...

    @abstractmethod
    async def save_owner(self, prop: Property, owner: PropertyOwner) -> Property: ...

    @abstractmethod
    async def update_owner(self, prop: Property, owner: PropertyOwner) -> Property: ...

    @abstractmethod
    async def save_price(self, prop: Property, price: PropertyPrice) -> Property: ...

    @abstractmethod
    async def save_image(self, prop: Property, image: PropertyImage) -> Property: ...

    @abstractmethod
    async def delete_image(self, prop: Property, image_id: UUID) -> Property: ...

    @abstractmethod
    async def list_active(self) -> list[Property]: ...

    @abstractmethod
    async def update_image_orders(
        self, prop: Property, image_orders: list[tuple[UUID, int]]
    ) -> Property: ...
