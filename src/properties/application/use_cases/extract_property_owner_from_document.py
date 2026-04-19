from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from properties.application.events.property_event import emit_property_updated
from properties.application.ports.document_data_extractor import DocumentDataExtractor
from properties.application.ports.document_parser import DocumentParser
from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.exceptions import DocumentExtractionError, PropertyNotFoundError
from properties.domain.models.property import Property
from properties.domain.models.property_owner import (
    CivilStatus,
    DocumentType,
    PropertyOwner,
)
from shared.events.ports import EventPublisher


class ExtractPropertyOwnerFromDocument:
    def __init__(
        self,
        property_repo: PropertyRepository,
        document_extractor: DocumentDataExtractor,
        document_parser: DocumentParser,
        domain_event_publisher: EventPublisher | None = None,
    ) -> None:
        self.property_repo = property_repo
        self.document_extractor = document_extractor
        self.document_parser = document_parser
        self.domain_event_publisher = domain_event_publisher

    async def execute(
        self,
        *,
        property_id: UUID,
        file_bytes: bytes,
        content_type: str,
        document_subtype: str = "cartao_cidadao",
    ) -> Property:
        prop = await self.property_repo.get_by_id(property_id)
        if not prop:
            raise PropertyNotFoundError(str(property_id))

        # Parse document first, then extract from text
        parsed_text = await self.document_parser.parse(file_bytes)
        data = await self.document_extractor.extract_property_owner_data(
            parsed_text, document_subtype
        )

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

        await self.property_repo.save_owner(prop, owner)
        refreshed = await self.property_repo.bump_aggregate_version(property_id)
        await emit_property_updated(self.domain_event_publisher, refreshed)
        return refreshed
