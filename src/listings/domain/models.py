from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID


class ListingType(StrEnum):
    SALE = "sale"
    PURCHASE = "purchase"


class Typology(StrEnum):
    HOUSE = "house"
    APARTMENT = "apartment"
    LAND = "land"
    RUIN = "ruin"


class PropertyStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    SOLD = "sold"
    RENTED = "rented"
    WITHDRAWN = "withdrawn"


@dataclass(frozen=True)
class PropertyCharacteristics:
    area_in_m2: float | None = None
    num_of_bedrooms: int | None = None
    num_of_bathrooms: int | None = None
    built_at: int | None = None
    energy_rating: str | None = None
    floor: int | None = None
    parking_spaces: int | None = None
    has_elevator: bool | None = None
    has_garden: bool | None = None
    has_pool: bool | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "PropertyCharacteristics":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass(frozen=True)
class PropertyImage:
    id: UUID
    property_id: UUID
    s3_key: str
    filename: str
    content_type: str
    size_bytes: int
    display_order: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class PropertyPrice:
    id: UUID
    property_id: UUID
    amount: Decimal
    listing_type: ListingType
    created_at: datetime
    updated_at: datetime


@dataclass
class ListedProperty:
    """Read-only property view for public listing. No owners."""

    id: UUID
    organization_id: UUID
    address: str
    listing_type: ListingType
    typology: Typology
    description: str | None
    characteristics: PropertyCharacteristics | None
    latitude: float | None
    longitude: float | None
    created_at: datetime
    updated_at: datetime
    prices: list[PropertyPrice] = field(default_factory=list)
    images: list[PropertyImage] = field(default_factory=list)
