from uuid import UUID

from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.models.property import Property, PropertyStatus
from properties.domain.models.property_image import PropertyImage
from properties.domain.models.property_owner import PropertyOwner
from properties.domain.models.property_price import PropertyPrice


class InMemoryPropertyRepository(PropertyRepository):
    def __init__(self) -> None:
        self._properties: dict[UUID, Property] = {}

    async def get_by_id(self, property_id: UUID) -> Property | None:
        return self._properties.get(property_id)

    async def list_by_organization(self, organization_id: UUID) -> list[Property]:
        return [p for p in self._properties.values() if p.organization_id == organization_id]

    async def list_active(self) -> list[Property]:
        return [p for p in self._properties.values() if p.status == PropertyStatus.ACTIVE]

    async def save(self, prop: Property) -> Property:
        self._properties[prop.id] = prop
        return prop

    async def save_owner(self, prop: Property, owner: PropertyOwner) -> Property:
        prop.add_owner(owner)
        self._properties[prop.id] = prop
        return prop

    async def update_owner(self, prop: Property, owner: PropertyOwner) -> Property:
        prop.owners = [owner if o.id == owner.id else o for o in prop.owners]
        self._properties[prop.id] = prop
        return prop

    async def save_price(self, prop: Property, price: PropertyPrice) -> Property:
        prop.add_price(price)
        self._properties[prop.id] = prop
        return prop

    async def save_image(self, prop: Property, image: PropertyImage) -> Property:
        prop.add_image(image)
        self._properties[prop.id] = prop
        return prop

    async def delete_image(self, prop: Property, image_id: UUID) -> Property:
        prop.remove_image(image_id)
        self._properties[prop.id] = prop
        return prop

    async def delete(self, property_id: UUID) -> None:
        self._properties.pop(property_id, None)

    async def update_image_orders(
        self, prop: Property, image_orders: list[tuple[UUID, int]]
    ) -> Property:
        order_map = dict(image_orders)
        for image in prop.images:
            if image.id in order_map:
                image.display_order = order_map[image.id]
        prop.images.sort(key=lambda i: i.display_order)
        self._properties[prop.id] = prop
        return prop
