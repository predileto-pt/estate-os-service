from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from property_management.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from property_management.domain.exceptions import PropertyNotFoundError
from property_management.domain.models.property import Property
from property_management.domain.models.property_owner import (
    CivilStatus,
    DocumentType,
    PropertyOwner,
)


class CreatePropertyOwner:
    def __init__(self, property_repo: PropertyRepository) -> None:
        self.property_repo = property_repo

    async def execute(
        self,
        *,
        property_id: UUID,
        full_name: str,
        civil_status: CivilStatus,
        address: str,
        nif: str,
        document_type: DocumentType,
        document_id: str,
        issued_by: str,
        issuing_district: str | None = None,
        date_of_birth: date,
    ) -> Property:
        prop = await self.property_repo.get_by_id(property_id)
        if not prop:
            raise PropertyNotFoundError(str(property_id))

        now = datetime.now(timezone.utc)
        owner = PropertyOwner(
            id=uuid4(),
            property_id=property_id,
            full_name=full_name,
            civil_status=civil_status,
            address=address,
            nif=nif,
            document_type=document_type,
            document_id=document_id,
            issued_by=issued_by,
            issuing_district=issuing_district,
            date_of_birth=date_of_birth,
            created_at=now,
            updated_at=now,
        )
        return await self.property_repo.save_owner(prop, owner)
