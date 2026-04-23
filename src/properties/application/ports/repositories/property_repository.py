from abc import ABC, abstractmethod
from uuid import UUID

from properties.domain.models.property import Property, PropertyStatus
from properties.domain.models.property_image import PropertyImage
from properties.domain.models.property_owner import PropertyOwner
from properties.domain.models.property_price import PropertyPrice


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
    async def delete(self, property_id: UUID) -> None:
        """Hard-delete a property and cascade owners, prices, and images."""
        ...

    @abstractmethod
    async def list_active(self) -> list[Property]: ...

    @abstractmethod
    async def update_image_orders(
        self, prop: Property, image_orders: list[tuple[UUID, int]]
    ) -> Property: ...

    @abstractmethod
    async def update_status(self, property_id: UUID, status: PropertyStatus) -> None:
        """Persist a status change on a single property. The aggregate version
        bump is driven separately by `bump_aggregate_version`, same as every
        other update-style write on this port."""
        ...

    @abstractmethod
    async def bump_aggregate_version(self, property_id: UUID) -> Property:
        """Atomically bump the property's aggregate_version + updated_at and
        return the refreshed aggregate.

        Called by every state-mutating use case AFTER its primary write
        succeeds, so the emitted event's snapshot reflects the new version.
        The version is the idempotency source for the listings projector.
        """
        ...
