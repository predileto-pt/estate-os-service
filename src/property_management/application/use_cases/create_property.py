from datetime import datetime, timezone
from uuid import UUID, uuid4

from property_management.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from property_management.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)


class CreateProperty:
    def __init__(self, property_repo: PropertyRepository) -> None:
        self.property_repo = property_repo

    async def execute(
        self,
        *,
        user_id: str,
        address: str,
        listing_type: ListingType,
        typology: Typology,
        description: str | None = None,
    ) -> Property:
        now = datetime.now(timezone.utc)
        prop = Property(
            id=uuid4(),
            user_id=UUID(user_id),
            address=address,
            listing_type=listing_type,
            typology=typology,
            status=PropertyStatus.DRAFT,
            description=description,
            created_at=now,
            updated_at=now,
        )
        return await self.property_repo.save(prop)
