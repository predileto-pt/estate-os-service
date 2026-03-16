from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from property_management.application.ports.document_data_extractor import DocumentDataExtractor
from property_management.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from property_management.domain.exceptions import DocumentExtractionError, PropertyNotFoundError
from property_management.domain.models.property import Property
from property_management.domain.models.property_owner import (
    CivilStatus,
    DocumentType,
    PropertyOwner,
)


class ExtractPropertyOwnerFromDocument:
    def __init__(
        self,
        property_repo: PropertyRepository,
        document_extractor: DocumentDataExtractor,
    ) -> None:
        self.property_repo = property_repo
        self.document_extractor = document_extractor

    async def execute(
        self,
        *,
        property_id: UUID,
        file_bytes: bytes,
        content_type: str,
    ) -> Property:
        prop = await self.property_repo.get_by_id(property_id)
        if not prop:
            raise PropertyNotFoundError(str(property_id))

        data = await self.document_extractor.extract_property_owner_data(file_bytes, content_type)

        try:
            now = datetime.now(timezone.utc)
            owner = PropertyOwner(
                id=uuid4(),
                property_id=property_id,
                full_name=data["full_name"],
                civil_status=CivilStatus(data["civil_status"]),
                address=data["address"],
                nif=data["nif"],
                document_type=DocumentType(data["document_type"]),
                document_id=data["document_id"],
                issued_by=data["issued_by"],
                issuing_district=data.get("issuing_district"),
                date_of_birth=date.fromisoformat(data["date_of_birth"]),
                created_at=now,
                updated_at=now,
            )
        except (KeyError, ValueError) as e:
            raise DocumentExtractionError(f"Invalid extracted data: {e}") from e

        return await self.property_repo.save_owner(prop, owner)
