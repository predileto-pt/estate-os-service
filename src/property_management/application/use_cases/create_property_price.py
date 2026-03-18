from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from property_management.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from property_management.domain.exceptions import PropertyNotFoundError
from property_management.domain.models.property import ListingType, Property
from property_management.domain.models.property_price import PropertyPrice


class CreatePropertyPrice:
    def __init__(self, property_repo: PropertyRepository) -> None:
        self.property_repo = property_repo

    async def execute(
        self,
        *,
        property_id: UUID,
        amount: Decimal,
        listing_type: ListingType,
    ) -> Property:
        prop = await self.property_repo.get_by_id(property_id)
        if not prop:
            raise PropertyNotFoundError(str(property_id))

        now = datetime.now(timezone.utc)
        price = PropertyPrice(
            id=uuid4(),
            property_id=property_id,
            amount=amount,
            listing_type=listing_type,
            created_at=now,
            updated_at=now,
        )
        return await self.property_repo.save_price(prop, price)
