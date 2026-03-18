from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from property_management.domain.models.property_characteristics import PropertyCharacteristics
from property_management.domain.models.property_owner import PropertyOwner
from property_management.domain.models.property_price import PropertyPrice


class ListingType(str, enum.Enum):
    SALE = "sale"
    PURCHASE = "purchase"


class Typology(str, enum.Enum):
    HOUSE = "house"
    APARTMENT = "apartment"
    LAND = "land"
    RUIN = "ruin"


class PropertyStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    SOLD = "sold"
    RENTED = "rented"
    WITHDRAWN = "withdrawn"


@dataclass
class Property:
    id: UUID
    organization_id: UUID
    address: str
    listing_type: ListingType
    typology: Typology
    status: PropertyStatus
    description: str | None
    created_at: datetime
    updated_at: datetime
    characteristics: PropertyCharacteristics | None = None
    latitude: float | None = None
    longitude: float | None = None
    owners: list[PropertyOwner] = field(default_factory=list)
    prices: list[PropertyPrice] = field(default_factory=list)

    def add_price(self, price: PropertyPrice) -> None:
        price.property_id = self.id
        self.prices.append(price)

    def get_price(self, price_id: UUID) -> PropertyPrice | None:
        return next((p for p in self.prices if p.id == price_id), None)

    def add_owner(self, owner: PropertyOwner) -> None:
        owner.property_id = self.id
        self.owners.append(owner)

    def get_owner(self, owner_id: UUID) -> PropertyOwner | None:
        return next((o for o in self.owners if o.id == owner_id), None)
