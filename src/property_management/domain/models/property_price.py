from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from property_management.domain.models.property import ListingType


@dataclass
class PropertyPrice:
    id: UUID
    property_id: UUID
    amount: Decimal
    listing_type: ListingType
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError(f"Price amount must be positive, got {self.amount}")
