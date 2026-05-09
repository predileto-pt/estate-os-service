from dataclasses import dataclass
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


# `ListedProperty` was the read-only domain type returned by the
# legacy `ListingRepository` (read mapping over the live `properties`
# table). It was collapsed into `PropertyListing` (the carried-state
# projection) when the routes migrated; this file now holds only the
# enums + `PropertyImage` / `PropertyPrice` / `PropertyCharacteristics`
# value objects that are still used elsewhere.
