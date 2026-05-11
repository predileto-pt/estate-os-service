from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from properties.domain.exceptions import (
    PropertyAddressInvalidError,
    PropertyNotPublishableError,
    PropertyNotUnpublishableError,
)
from properties.domain.models.property_characteristics import PropertyCharacteristics
from properties.domain.models.property_image import PropertyImage
from properties.domain.models.property_owner import PropertyOwner
from properties.domain.models.property_price import PropertyPrice


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
    title: str
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
    images: list[PropertyImage] = field(default_factory=list)

    # Monotonic per-Property counter. Bumped in the same transaction as every
    # state-mutating write. Used as the idempotency source for the
    # `property_listings` projector — events with a lower
    # `source_aggregate_version` than the stored value are dropped.
    aggregate_version: int = 0

    def bump_version(self) -> None:
        """Increment the aggregate version. Called inside write-path use cases
        on the same transaction as the state change they're broadcasting."""
        self.aggregate_version += 1

    def publish(self) -> None:
        """Flip status to ACTIVE if the aggregate is publishable.

        Raises PropertyNotPublishableError with a list of machine-readable
        reason codes when the aggregate is not ready. Does NOT bump
        aggregate_version — the use case drives that via the repo's atomic
        bump_aggregate_version method, matching UpdatePropertyOwnerContact.
        """
        reasons: list[str] = []
        if self.status not in (PropertyStatus.DRAFT, PropertyStatus.WITHDRAWN):
            reasons.append(f"cannot_publish_from_status:{self.status.value}")
        if not self.address.strip():
            reasons.append("missing_address")
        if not self.prices:
            reasons.append("missing_price")
        if not self.owners:
            reasons.append("missing_owner")
        if not self.images:
            reasons.append("missing_image")
        if reasons:
            raise PropertyNotPublishableError(reasons)
        self.status = PropertyStatus.ACTIVE

    def unpublish(self) -> None:
        """Flip status from ACTIVE back to DRAFT — takes the property
        off the public listings.

        Symmetric to `publish()`: domain-only state transition; the use
        case calls `update_status` and `bump_aggregate_version` on the
        repo. Raises `PropertyNotUnpublishableError` if the property
        isn't currently ACTIVE (no other status can be unpublished —
        DRAFT/WITHDRAWN/SOLD/RENTED already aren't on the public site).
        """
        if self.status is not PropertyStatus.ACTIVE:
            raise PropertyNotUnpublishableError(
                [f"cannot_unpublish_from_status:{self.status.value}"]
            )
        self.status = PropertyStatus.DRAFT

    def update_address(self, new_address: str) -> None:
        """Replace the property's address. Strips surrounding whitespace and
        rejects empty input. Does NOT bump aggregate_version — the use case
        drives that via the repo's atomic bump_aggregate_version method,
        matching every other update-style use case in this context.
        """
        cleaned = new_address.strip()
        if not cleaned:
            raise PropertyAddressInvalidError()
        self.address = cleaned

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

    def add_image(self, image: PropertyImage) -> None:
        image.property_id = self.id
        self.images.append(image)

    def get_image(self, image_id: UUID) -> PropertyImage | None:
        return next((i for i in self.images if i.id == image_id), None)

    def remove_image(self, image_id: UUID) -> PropertyImage | None:
        image = self.get_image(image_id)
        if image:
            self.images.remove(image)
        return image
